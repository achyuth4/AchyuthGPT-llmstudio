import os

os.environ["OMP_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"
os.environ["OPENBLAS_NUM_THREADS"] = "1"
os.environ["VECLIB_MAXIMUM_THREADS"] = "1"
os.environ["NUMEXPR_NUM_THREADS"] = "1"
os.environ["TOKENIZERS_PARALLELISM"] = "false"

import argparse
import gc
import logging
import sys
import time
from datetime import timedelta
from distutils import util
from typing import Any, Callable, Dict, Tuple

import numpy as np
import pandas as pd
import torch
from accelerate import (
    Accelerator,
    DistributedDataParallelKwargs,
    DistributedType,
    FullyShardedDataParallelPlugin,
    InitProcessGroupKwargs,
    DeepSpeedPlugin,
)
from accelerate.utils.deepspeed import HfDeepSpeedConfig

from torch.distributed.fsdp.fully_sharded_data_parallel import (
    CPUOffload,
    MixedPrecision,
)
from tqdm import tqdm

from llm_studio.src.loggers import MainLogger
from llm_studio.src.utils.config_utils import (
    load_config_py,
    load_config_yaml,
    save_config_yaml,
)
from llm_studio.src.utils.data_utils import (
    get_data,
    get_inference_batch_size,
    get_train_dataloader,
    get_train_dataset,
    get_val_dataloader,
    get_val_dataset,
)
from llm_studio.src.utils.exceptions import LLMTrainingException
from llm_studio.src.utils.export_utils import save_prediction_outputs
from llm_studio.src.utils.gpu_utils import sync_across_processes
from llm_studio.src.utils.logging_utils import (
    TqdmToLogger,
    initialize_logging,
    log_plot,
    write_flag,
)
from llm_studio.src.utils.modeling_utils import (
    compute_metric,
    get_number_of_validation_epochs,
    get_optimizer,
    get_scheduler,
    load_checkpoint,
    run_inference,
    save_checkpoint,
    save_predictions,
)
from llm_studio.src.utils.utils import kill_ddp_processes, set_environment, set_seed

logger = logging.getLogger(__name__)


def run_eval(
    cfg,
    accelerator: Accelerator,
    model: torch.nn.Module,
    val_dataloader: torch.utils.data.DataLoader,
    val_df: pd.DataFrame,
    mode: str = "validation",
) -> Tuple:
    """Runs the evaluation loop.

    Args:
        cfg: config object
        model: trained model
        val_dataloader: validation Dataloader
        val_df: validation DataFrame
        mode: validation

    Returns:
        Validation loss
        Validation metric
    """

    with torch.no_grad():
        model.eval()
        val_data: Dict[str, Any] = run_inference(
            cfg, accelerator, model, val_dataloader, mode
        )  # type: ignore

    # Sync validation predictions across GPUs
    if cfg.environment._distributed != DistributedType.NO:
        for key, value in val_data.items():
            val_data[key] = sync_across_processes(
                value, cfg.environment._world_size, group=cfg.environment._cpu_comm
            )

    torch.inference_mode(mode=True)
    # Drop any extra observations
    for k, v in val_data.items():
        val_data[k] = v[: len(val_dataloader.dataset)]  # type: ignore

    if cfg.environment._local_rank == 0:
        val_data = val_dataloader.dataset.postprocess_output(  # type: ignore
            cfg=cfg, df=val_df, output=val_data
        )

    val_loss = 0.0
    val_metric = 0.0
    if cfg.environment._local_rank == 0:
        # Calculate validation loss
        if "loss" in val_data:
            assert isinstance(val_data["loss"], torch.Tensor)
            val_losses = val_data["loss"].float().cpu().numpy()
            val_loss = np.mean(val_losses)
            logger.info(f"Mean {mode} loss: {np.mean(val_losses):.5f}")
            cfg.logging._logger.log(
                mode, "loss", val_loss, step=cfg.environment._curr_step
            )

        # Calculate validation metric
        metric_func, _ = cfg.prediction.metric_class.get(cfg.prediction.metric)
        val_metric = compute_metric(metric_func, cfg, val_data, val_df)

        logger.info(f"{mode.capitalize()} {cfg.prediction.metric}: {val_metric:.5f}")
        cfg.logging._logger.log(
            mode, cfg.prediction.metric, val_metric, step=cfg.environment._curr_step
        )

        # Log plots
        if val_df is not None:
            plot = cfg.logging.plots_class.plot_validation_predictions(
                val_outputs=val_data, cfg=cfg, val_df=val_df, mode="validation"
            )
            log_plot(cfg, plot, "validation_predictions")

        save_predictions(cfg, val_data, val_dataloader, val_df, mode)

    accelerator.wait_for_everyone()

    torch.inference_mode(mode=False)

    return val_loss, val_metric


def run_train_and_val(
    cfg: Any,
    accelerator: Accelerator,
    model: torch.nn.Module,
    train_dataloader: torch.utils.data.DataLoader,
    val_dataloader: torch.utils.data.DataLoader,
    val_df: pd.DataFrame,
):
    """Runs the training loop.

    Args:
        cfg: config object
        model: model
        train_dataloader: training Dataloader
        train_df: train DataFrame
        val_dataloader: validation Dataloader
        val_df: validation DataFrame

    Returns:
        Validation loss
        Validation metric
    """

    model = accelerator.prepare(model)

    # Prepare optimizer and scheduler after preparing the model
    # https://huggingface.co/docs/accelerate/usage_guides/fsdp#a-few-caveats-to-be-aware-of
    optimizer = get_optimizer(model=model, cfg=cfg)
    scheduler = get_scheduler(
        cfg=cfg, optimizer=optimizer, epoch_steps=len(train_dataloader)
    )

    # Prepare everything for training
    model, optimizer, train_dataloader, val_dataloader, scheduler = accelerator.prepare(
        model, optimizer, train_dataloader, val_dataloader, scheduler
    )
    epoch_steps = len(train_dataloader)

    optimizer.zero_grad(set_to_none=True)

    # Prepare NLP Augmentation
    nlp_augment = None
    if hasattr(cfg.augmentation, "nlp_augmentations_class"):
        nlp_augment = cfg.augmentation.nlp_augmentations_class(cfg=cfg)

    start_epoch = 0

    _, metric_mode = cfg.prediction.metric_class.get(cfg.prediction.metric)
    objective_op: Callable[[float, float], bool]
    if metric_mode == "max":
        best_val_metric = -np.inf
        objective_op = np.greater
    else:
        best_val_metric = np.inf
        objective_op = np.less

    num_updates = 0

    batch = None
    if cfg.training.evaluate_before_training:
        val_loss, val_metric = run_eval(
            cfg=cfg,
            accelerator=accelerator,
            model=model,
            val_dataloader=val_dataloader,
            val_df=val_df,
        )

    for epoch in range(start_epoch, cfg.training.epochs):
        set_seed(
            cfg.environment._seed
            + epoch * cfg.environment._world_size * cfg.environment.number_of_workers
            + cfg.environment._local_rank * cfg.environment.number_of_workers
        )
        if cfg.environment._local_rank == 0:
            logger.info(f"Training Epoch: {epoch + 1} / {cfg.training.epochs}")

        if cfg.training.evaluation_epochs == 1:
            tqdm_out = TqdmToLogger(logger, level=logging.INFO)
            progress_bar = tqdm(
                total=epoch_steps,
                disable=cfg.environment._local_rank != 0,
                file=tqdm_out,
                ascii=True,
                desc="train loss",
                mininterval=0,
            )
        else:
            logger.info(
                "Training progress bar is not "
                "displayed (evaluation epoch is not set to 1)"
            )

        losses = []
        model.train()

        log_update_steps = max(epoch_steps // 20, 1)
        evaluation_step = int(epoch_steps * cfg.training.evaluation_epochs)
        for itr, data in enumerate(train_dataloader):
            num_updates += 1
            cfg.environment._curr_step += (
                cfg.training.batch_size * cfg.environment._world_size
            )

            # Batch to device
            batch = cfg.dataset.dataset_class.batch_to_device(
                data, cfg.environment._device
            )

            # NLP augmentation
            if nlp_augment is not None:
                batch = nlp_augment(batch)

            # Plot first batch
            if epoch == 0 and itr == 0 and cfg.environment._local_rank == 0:
                plot = cfg.logging.plots_class.plot_batch(batch=batch, cfg=cfg)
                log_plot(cfg, plot, "train_data")

            # Forward pass
            with accelerator.accumulate(model):
                with accelerator.autocast():
                    output_dict = model.forward(batch)

            loss = output_dict["loss"]
            if ~np.isfinite(loss.item()) and (num_updates > 20):
                raise LLMTrainingException(
                    "NaN caught in loss during training. "
                    "Please, reduce learning rate, change dtype, "
                    "or disable mixed precision. "
                    "Alternatively, gradient clipping may help to stabilize training."
                )
            losses.append(loss.item())

            # Backward pass
            accelerator.backward(loss)
            if (cfg.training.gradient_clip > 0) and accelerator.sync_gradients:
                accelerator.clip_grad_norm_(
                    model.parameters(), cfg.training.gradient_clip
                )
            optimizer.step()
            optimizer.zero_grad(set_to_none=True)

            if scheduler is not None:
                scheduler.step()

            if cfg.environment._local_rank == 0:
                cfg.logging._logger.log(
                    "train", "loss", losses[-1], step=cfg.environment._curr_step
                )
                cfg.logging._logger.log(
                    "meta",
                    "lr",
                    optimizer.param_groups[0]["lr"],
                    step=cfg.environment._curr_step,
                )
                if cfg.training.differential_learning_rate_layers:
                    cfg.logging._logger.log(
                        "meta",
                        "lr_diff",
                        optimizer.param_groups[2]["lr"],
                        step=cfg.environment._curr_step,
                    )

                cfg.logging._logger.log(
                    "internal",
                    "current_step",
                    cfg.environment._curr_step,
                    step=cfg.environment._curr_step,
                )

                # Show logs each 5% of the epoch (only if doing per epoch evaluation)
                if cfg.training.evaluation_epochs == 1 and (
                    (itr + 1) % log_update_steps == 0 or itr == epoch_steps - 1
                ):
                    progress_bar.set_description(
                        f"train loss: {np.mean(losses[-10:]):.2f}", refresh=False
                    )
                    if (itr + 1) % log_update_steps == 0:
                        progress_bar.update(log_update_steps)
                    else:
                        progress_bar.update(epoch_steps % log_update_steps)

            # Validation loop
            if (itr + 1) % evaluation_step == 0:
                if cfg.training.evaluation_epochs == 1:
                    progress_bar.close()

                val_loss, val_metric = run_eval(
                    cfg=cfg,
                    accelerator=accelerator,
                    model=model,
                    val_dataloader=val_dataloader,
                    val_df=val_df,
                )
                if cfg.environment._local_rank == 0:
                    if (
                        objective_op(val_metric, best_val_metric)
                        and cfg.training.save_best_checkpoint
                    ):
                        if cfg.environment._local_rank == 0:
                            checkpoint_path = cfg.output_directory
                            logger.info(
                                f"Saving best model checkpoint: "
                                f"val_{cfg.prediction.metric} {best_val_metric:.5} -> "
                                f"{val_metric:.5} to {checkpoint_path}"
                            )

                            save_checkpoint(model=model, path=checkpoint_path, cfg=cfg)
                        best_val_metric = val_metric

                model.train()

        if cfg.training.evaluation_epochs == 1:
            progress_bar.close()
            del progress_bar

        accelerator.wait_for_everyone()

        if cfg.environment._local_rank == 0:
            cfg.logging._logger.log(
                "internal", "epoch", epoch + 1, step=cfg.environment._curr_step
            )

    accelerator.wait_for_everyone()

    return val_loss, val_metric


def run(cfg: Any) -> None:
    """Runs the routine.

    Args:
        cfg: config object with all the hyperparameters
    """

    os.makedirs(cfg.output_directory, exist_ok=True)

    # Force evaluation if user trains 0 epochs
    cfg.training.evaluate_before_training = (
        cfg.training.evaluate_before_training or cfg.training.epochs == 0
    )

    # Set the random seed for reproducibility
    # either random seed when user set it -1 or deterministic user chosen seed
    if cfg.environment.seed < 0:
        cfg.environment._seed = np.random.randint(1_000_000)
    else:
        cfg.environment._seed = cfg.environment.seed

    # Initialize the accelerator
    ddp_kwargs = DistributedDataParallelKwargs(
        find_unused_parameters=cfg.environment.find_unused_parameters
    )
    init_process_kwargs = InitProcessGroupKwargs(
        backend="nccl", init_method="env://", timeout=timedelta(seconds=800)
    )
    if cfg.environment.use_fsdp:
        mixed_precision_policy = MixedPrecision(
            param_dtype=torch.float16,
            reduce_dtype=torch.float16,
            buffer_dtype=torch.float16,
        )
        fsdp_plugin = FullyShardedDataParallelPlugin(
            cpu_offload=CPUOffload(offload_params=True),
            mixed_precision_policy=mixed_precision_policy,
        )
    else:
        fsdp_plugin = None

    if cfg.environment.use_deepspeed:
        deepspeed_plugin = DeepSpeedPlugin(
            # hf_ds_config=deepspeed_config,
            zero_stage=2,
            gradient_accumulation_steps=cfg.training.grad_accumulation,
            offload_optimizer_device="cpu",
            # offload_param_device="cpu",
            # zero3_init_flag=True,
            # zero3_save_16bit_model=True,
        )
        deepspeed_plugin.deepspeed_config[
            "train_micro_batch_size_per_gpu"
        ] = cfg.training.batch_size
        deepspeed_plugin.deepspeed_config["optimizer"] = {
            "type": "AdamW",
            "params": {
                "lr": cfg.training.learning_rate,
                "betas": [0.8, 0.999],
                "eps": 1e-8,
                "weight_decay": 3e-7,
            },
        }
    else:
        deepspeed_plugin = None

    if cfg.environment.mixed_precision:
        mixed_precision = "fp16"
    else:
        mixed_precision = "no"

    accelerator = Accelerator(
        fsdp_plugin=fsdp_plugin,
        deepspeed_plugin=deepspeed_plugin,
        mixed_precision=mixed_precision,  # ["no", "fp16", "bf16", "fp8"]
        gradient_accumulation_steps=cfg.training.grad_accumulation,
        kwargs_handlers=[ddp_kwargs, init_process_kwargs],
    )

    cfg.environment._local_rank = accelerator.local_process_index
    cfg.environment._rank = accelerator.process_index
    cfg.environment._device = accelerator.device
    cfg.environment._distributed = accelerator.distributed_type
    logger.info(cfg.environment._distributed)
    cfg.environment._device = accelerator.device
    cfg.environment._world_size = accelerator.num_processes

    if cfg.environment._distributed != DistributedType.NO:
        logger.info(
            f"Training in distributed mode with multiple processes, "
            f"1 GPU per process. Process {cfg.environment._rank}, "
            f"total: {cfg.environment._world_size} "
            f"local rank: {cfg.environment._local_rank}."
        )

    set_seed(cfg.environment._seed)
    if cfg.environment._local_rank == 0:
        logger.info(f"Global random seed: {cfg.environment._seed}")

    cfg = set_environment(cfg)

    # we need to get train dataframe and number of labels if not set or in training mode
    if cfg.environment._local_rank == 0:
        logger.info("Preparing the data...")
    train_df, val_df = get_data(cfg)

    if (
        len(val_df) > int(os.getenv("GPT_EVAL_MAX", 100))
        and "GPT" in cfg.prediction.metric
    ):
        logger.warning(
            f"More than {os.getenv('GPT_EVAL_MAX', 100)} validation records. "
            "Safeguarding against OpenAI API costs. Setting metric to BLEU. "
            "Change GPT_EVAL_MAX to run GPT validation."
        )
        cfg.prediction.metric = "BLEU"

    # prepare data
    if cfg.environment._local_rank == 0:
        logger.info("Preparing train and validation data")
    train_dataset = get_train_dataset(train_df=train_df, cfg=cfg)
    val_dataset = get_val_dataset(val_df=val_df, cfg=cfg)
    train_dataloader = get_train_dataloader(train_ds=train_dataset, cfg=cfg)
    val_dataloader = get_val_dataloader(val_ds=val_dataset, cfg=cfg)

    if cfg.environment._local_rank == 0:
        total_training_steps = (
            cfg.training.epochs * len(train_dataloader) * cfg.training.batch_size
        )

        num_eval_epochs = get_number_of_validation_epochs(
            training_epochs=cfg.training.epochs,
            evaluation_epochs=cfg.training.evaluation_epochs,
        )
        val_batch_size = get_inference_batch_size(cfg)
        # if zero shot, validate once before training
        total_validation_steps = (
            len(val_dataloader)
            * (num_eval_epochs + int(cfg.training.evaluate_before_training))
            * val_batch_size
        )

    # Prepare model
    with torch.device(cfg.environment._device):
        model = cfg.architecture.model_class(cfg)

        # load model weights
        if cfg.architecture.pretrained_weights != "":
            # Do not load strictly if continue training from the previous experiment
            load_checkpoint(cfg, model, strict=cfg.training.epochs == -1)

    if cfg.architecture.force_embedding_gradients:
        for module in model.modules():
            if isinstance(module, torch.nn.Embedding):
                for param in module.parameters():
                    param.requires_grad = True
                    param.data = param.data.float()

    if cfg.environment.compile_model:
        if cfg.environment._distributed != DistributedType.NO:
            model.module.backbone = torch.compile(model.module.backbone)
        else:
            model.backbone = torch.compile(model.backbone)

    # Force settings when saving best checkpoint
    if cfg.training.save_best_checkpoint:
        cfg.training.evaluation_epochs = 1
        cfg.training.train_validation_data = False

    # reset steps
    cfg.environment._curr_step = 0
    cfg.environment._curr_val_step = 0

    gc.collect()

    global_start_time = time.time()
    if cfg.environment._local_rank == 0:
        # re-save cfg
        save_config_yaml(f"{cfg.output_directory}/cfg.yaml", cfg)

        cfg.logging._logger = MainLogger(cfg)

        cfg.logging._logger.log(
            "internal", "total_training_steps", total_training_steps, step=0
        )

        cfg.logging._logger.log(
            "internal", "total_validation_steps", total_validation_steps, step=0
        )

        cfg.logging._logger.log(
            "internal",
            "global_start_time",
            global_start_time,
            step=cfg.environment._curr_step,
        )
        # re-save config
        save_config_yaml(f"{cfg.output_directory}/cfg.yaml", cfg)

    val_loss, val_metric = run_train_and_val(
        cfg=cfg,
        accelerator=accelerator,
        model=model,
        train_dataloader=train_dataloader,
        val_dataloader=val_dataloader,
        val_df=val_df,
    )

    # Unwrap model
    model = accelerator.unwrap_model(model)

    # reset external logging
    if cfg.environment._local_rank == 0:
        cfg.logging._logger.reset_external()

    experiment_path = f"{cfg.output_directory}"

    if cfg.environment._local_rank == 0:
        if not cfg.training.save_best_checkpoint:
            checkpoint_path = cfg.output_directory

            logger.info(
                f"Saving last model checkpoint: "
                f"val_loss {val_loss:.5}, val_{cfg.prediction.metric} "
                f"{val_metric:.5} to {checkpoint_path}"
            )

            save_checkpoint(model=model, path=checkpoint_path, cfg=cfg)

        save_config_yaml(f"{cfg.output_directory}/cfg.yaml", cfg)

    if cfg.environment._local_rank == 0:
        save_prediction_outputs(cfg.experiment_name, experiment_path)

    if cfg.environment._local_rank == 0:
        flag_path = os.path.join(cfg.output_directory, "flags.json")
        write_flag(flag_path, "status", "finished")
        time_took = time.time() - global_start_time
        if time_took > 86400:
            time_took_formatted = time.strftime(
                "%-jd %H:%M:%S", time.gmtime(float(time_took))
            )
        else:
            time_took_formatted = time.strftime(
                "%H:%M:%S", time.gmtime(float(time_took))
            )
        write_flag(flag_path, "info", f"Runtime: {time_took_formatted}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="")
    parser.add_argument(
        "-C", "--config", help="config filename", default=argparse.SUPPRESS
    )
    parser.add_argument("-Y", "--yaml", help="yaml filename", default=argparse.SUPPRESS)
    parser_args, unknown = parser.parse_known_args(sys.argv)

    if "config" in parser_args:
        cfg = load_config_py(parser_args.config)
    elif "yaml" in parser_args:
        cfg = load_config_yaml(parser_args.yaml)
    else:
        raise ValueError("Please, provide a configuration file")

    extra_args = []
    for arg_orig in unknown:
        if arg_orig.startswith(("-", "--")):
            arg = arg_orig.replace("-", "").split(".")
            try:
                arg_type = getattr(cfg, arg[0]).get_annotations()[arg[1]]
            except (AttributeError, KeyError):
                continue
            if arg_type == bool:
                parser.add_argument(arg_orig, type=util.strtobool)
            else:
                parser.add_argument(arg_orig, type=arg_type)
            extra_args.append(arg)

    args = parser.parse_args()

    for arg in extra_args:
        value = getattr(args, ".".join(arg))
        setattr(getattr(cfg, arg[0]), arg[1], value)

    out_dir = cfg.output_directory
    os.makedirs(out_dir, exist_ok=True)

    initialize_logging(cfg)

    try:
        run(cfg=cfg)
    except Exception:
        logging.error("Exception occurred during the run:", exc_info=True)
        kill_ddp_processes()
