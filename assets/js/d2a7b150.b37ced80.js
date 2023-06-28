"use strict";(self.webpackChunksite=self.webpackChunksite||[]).push([[145],{3905:(e,t,n)=>{n.d(t,{Zo:()=>u,kt:()=>d});var r=n(7294);function o(e,t,n){return t in e?Object.defineProperty(e,t,{value:n,enumerable:!0,configurable:!0,writable:!0}):e[t]=n,e}function a(e,t){var n=Object.keys(e);if(Object.getOwnPropertySymbols){var r=Object.getOwnPropertySymbols(e);t&&(r=r.filter((function(t){return Object.getOwnPropertyDescriptor(e,t).enumerable}))),n.push.apply(n,r)}return n}function i(e){for(var t=1;t<arguments.length;t++){var n=null!=arguments[t]?arguments[t]:{};t%2?a(Object(n),!0).forEach((function(t){o(e,t,n[t])})):Object.getOwnPropertyDescriptors?Object.defineProperties(e,Object.getOwnPropertyDescriptors(n)):a(Object(n)).forEach((function(t){Object.defineProperty(e,t,Object.getOwnPropertyDescriptor(n,t))}))}return e}function p(e,t){if(null==e)return{};var n,r,o=function(e,t){if(null==e)return{};var n,r,o={},a=Object.keys(e);for(r=0;r<a.length;r++)n=a[r],t.indexOf(n)>=0||(o[n]=e[n]);return o}(e,t);if(Object.getOwnPropertySymbols){var a=Object.getOwnPropertySymbols(e);for(r=0;r<a.length;r++)n=a[r],t.indexOf(n)>=0||Object.prototype.propertyIsEnumerable.call(e,n)&&(o[n]=e[n])}return o}var l=r.createContext({}),c=function(e){var t=r.useContext(l),n=t;return e&&(n="function"==typeof e?e(t):i(i({},t),e)),n},u=function(e){var t=c(e.components);return r.createElement(l.Provider,{value:t},e.children)},s="mdxType",m={inlineCode:"code",wrapper:function(e){var t=e.children;return r.createElement(r.Fragment,{},t)}},g=r.forwardRef((function(e,t){var n=e.components,o=e.mdxType,a=e.originalType,l=e.parentName,u=p(e,["components","mdxType","originalType","parentName"]),s=c(n),g=o,d=s["".concat(l,".").concat(g)]||s[g]||m[g]||a;return n?r.createElement(d,i(i({ref:t},u),{},{components:n})):r.createElement(d,i({ref:t},u))}));function d(e,t){var n=arguments,o=t&&t.mdxType;if("string"==typeof e||o){var a=n.length,i=new Array(a);i[0]=g;var p={};for(var l in t)hasOwnProperty.call(t,l)&&(p[l]=t[l]);p.originalType=e,p[s]="string"==typeof e?e:o,i[1]=p;for(var c=2;c<a;c++)i[c]=n[c];return r.createElement.apply(null,i)}return r.createElement.apply(null,n)}g.displayName="MDXCreateElement"},2026:(e,t,n)=>{n.r(t),n.d(t,{assets:()=>l,contentTitle:()=>i,default:()=>m,frontMatter:()=>a,metadata:()=>p,toc:()=>c});var r=n(7462),o=(n(7294),n(3905));const a={},i="Publish model to HuggingFace",p={unversionedId:"guide/experiments/export-trained-model",id:"guide/experiments/export-trained-model",title:"Publish model to HuggingFace",description:"If you\u2019re ready to share your trained model with a broader community, H2O LLM Studio allows you to export the fine-tuned model to Hugging Face with a single click.",source:"@site/docs/guide/experiments/export-trained-model.md",sourceDirName:"guide/experiments",slug:"/guide/experiments/export-trained-model",permalink:"/guide/experiments/export-trained-model",draft:!1,tags:[],version:"current",frontMatter:{},sidebar:"defaultSidebar",previous:{title:"Compare experiments",permalink:"/guide/experiments/compare-experiments"},next:{title:"FAQs",permalink:"/faqs"}},l={},c=[],u={toc:c},s="wrapper";function m(e){let{components:t,...a}=e;return(0,o.kt)(s,(0,r.Z)({},u,a,{components:t,mdxType:"MDXLayout"}),(0,o.kt)("h1",{id:"publish-model-to-huggingface"},"Publish model to HuggingFace"),(0,o.kt)("p",null,"If you\u2019re ready to share your trained model with a broader community, H2O LLM Studio allows you to export the fine-tuned model to ",(0,o.kt)("a",{parentName:"p",href:"https://huggingface.co/"},"Hugging Face")," with a single click."),(0,o.kt)("admonition",{title:"note",type:"info"},(0,o.kt)("p",{parentName:"admonition"},"Before publishing your model to the Hugging Face Hub, you need to have an API key with the write access. To obtain an API token with write access, you can follow the ",(0,o.kt)("a",{parentName:"p",href:"https://huggingface.co/docs/hub/security-tokens"},"instructions provided by Hugging Face"),", which involve creating an account, logging in, and generating an access token with the appropriate permission.")),(0,o.kt)("p",null,"To publish a trained model to Hugging Face Hub:"),(0,o.kt)("ol",null,(0,o.kt)("li",{parentName:"ol"},(0,o.kt)("p",{parentName:"li"},"On the H2O LLM Studio left-navigation pane, click ",(0,o.kt)("strong",{parentName:"p"},"View experiments"),". You will see the experiments table with a list of all the experiments you have launched so far. ")),(0,o.kt)("li",{parentName:"ol"},(0,o.kt)("p",{parentName:"li"},"Click the name of the experiment that you want to export the model.")),(0,o.kt)("li",{parentName:"ol"},(0,o.kt)("p",{parentName:"li"},"Click ",(0,o.kt)("strong",{parentName:"p"},"Push checkpoint to huggingface"),".")),(0,o.kt)("li",{parentName:"ol"},(0,o.kt)("p",{parentName:"li"},"Enter the ",(0,o.kt)("strong",{parentName:"p"},"Account name")," on Hugging Face that you want to push the model. Leaving it empty will push it to the default user account.")),(0,o.kt)("li",{parentName:"ol"},(0,o.kt)("p",{parentName:"li"},"Enter the ",(0,o.kt)("strong",{parentName:"p"},"Huggingface API")," Key with the write access.")),(0,o.kt)("li",{parentName:"ol"},(0,o.kt)("p",{parentName:"li"},"Click ",(0,o.kt)("strong",{parentName:"p"},"Export"),"."),(0,o.kt)("p",{parentName:"li"},(0,o.kt)("img",{alt:"export model to hugging face",src:n(7555).Z,width:"2880",height:"1296"})))))}m.isMDXComponent=!0},7555:(e,t,n)=>{n.d(t,{Z:()=>r});const r=n.p+"assets/images/export-model-to-huggingface-751d5a3594cb0f0ddfc8f7716aceafa0.png"}}]);