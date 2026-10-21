"use strict";
const $ = id => document.getElementById(id);
let state, selected, prepared;
const money = cents => new Intl.NumberFormat("en-CA", {style:"currency",currency:"CAD",maximumFractionDigits:0}).format(cents/100);
const percent = value => value == null ? "—" : (value*100).toFixed(1)+"%";
const pretty = value => JSON.stringify(value,null,2);
function el(tag, text, cls) {const n=document.createElement(tag);if(text!=null)n.textContent=String(text);if(cls)n.className=cls;return n;}
function clear(id){const node=$(id);node.replaceChildren();return node;}
function chip(text){return el("span",text,"tag "+text);}
function message(text,error=false){$("notice").textContent=text;$("notice").className="notice"+(error?" error":"");}
async function api(path,body){const options=body===undefined?{}:{method:"POST",headers:{"Content-Type":"application/json","X-Demo-Intent":"operator"},body:JSON.stringify(body)};const r=await fetch("/api/"+path,options);const data=await r.json();if(!r.ok)throw Error(data.error||"Request failed");return data;}
async function task(fn){try{await fn();}catch(error){message(error.message,true);}}
function openView(name){document.querySelectorAll(".view").forEach(n=>n.classList.toggle("active",n.id===name));document.querySelectorAll(".nav").forEach(n=>n.classList.toggle("active",n.dataset.view===name));$("current-view").textContent={overview:"Pipeline overview",workspace:"Account workbench",inbound:"Inbound routing",recovery:"Execution & recovery",proof:"Native & AI evidence"}[name];window.scrollTo(0,0);}
document.querySelectorAll("[data-view]").forEach(n=>n.onclick=()=>openView(n.dataset.view));
document.querySelectorAll("[data-open]").forEach(n=>n.onclick=()=>openView(n.dataset.open));
function current(){return state.accounts.find(a=>a.id===selected);}
function actionFor(id){return state.actions.find(a=>a.account_id===id);}
function selectAccount(id){selected=id;prepared=null;$("account-select").value=id;renderAccount();}
function metric(label,value,note){const n=el("div",null,"metric");n.append(el("div",label,"metric-label"),el("strong",value),el("small",note));return n;}
function row(values,heading=false){const n=el("div",null,"comparison-row"+(heading?" heading-row":""));values.forEach(v=>n.append(el("span",v)));return n;}
function renderOverview(){
 const m=state.measurement,t=m.arms.treatment,h=m.arms.holdout;
 clear("metrics").append(metric("Assigned accounts",t.assigned+h.assigned,"Brand-scoped · frozen allocation"),metric("Qualified meetings",t.qualified_meetings+h.qualified_meetings,"Mature 30-day account windows"),metric("Accepted opportunities",t.accepted_opportunities+h.accepted_opportunities,"Distinct CRM business identities"),metric("Qualified pipeline",money(t.pipeline_cents+h.pipeline_cents),"Synthetic accepted value · not revenue"));
 const c=clear("comparison");c.append(row(["Eligible accounts","Treatment","Holdout"],true),row(["Mature denominator",t.mature_accounts,h.mature_accounts]),row(["Enrolled accounts",t.exposed_accounts,h.exposed_accounts]),row(["Accounts with meeting",t.accounts_with_meetings,h.accounts_with_meetings]),row(["Meeting rate",percent(t.meeting_rate),percent(h.meeting_rate)]),row(["Accepted opportunities",t.accepted_opportunities,h.accepted_opportunities]),row(["Pipeline / assigned account",money(t.pipeline_per_account_cents||0),money(h.pipeline_per_account_cents||0)]));
 $("integrity").textContent=state.reconciliation.safe_to_resume?"RECONCILED":"FAIL CLOSED";
 const assurance=clear("assurance");[["Independent remote effects",state.reconciliation.remote_effects+" verified"],["Ownership / consent changes",state.actions.filter(a=>a.status==="blocked").length+" blocked actions"],["Holdout leakage",m.leakage_accounts.length+" enrolled accounts"],["Audit-chain integrity",state.audit_valid?"Verified":"Failed"]].forEach(([label,value])=>{const n=el("div",null,"assurance-item");n.append(el("span",label),el("b",value));assurance.append(n);});
 const table=clear("accounts");const filter=$("brand-filter").value;
 state.accounts.filter(a=>filter==="all"||a.brand===filter).forEach(a=>{const tr=el("tr");let td=el("td");td.append(el("strong",a.name),el("small",a.brand.toUpperCase()+" · "+a.domain));tr.append(td);td=el("td");td.append(el("strong",a.score.fit+" / "+a.score.intent.toFixed(0)),el("small",a.score.eligible?"Qualified":"Review required"));tr.append(td,el("td",a.owner||"Unassigned"));td=el("td");td.append(chip(a.cohort?.arm||"not assigned"));tr.append(td);td=el("td");td.append(chip(actionFor(a.id)?.status||"not enrolled"));tr.append(td);td=el("td");const b=el("button","Inspect ↗","button small secondary");b.onclick=()=>{selectAccount(a.id);openView("workspace");};td.append(b);tr.append(td);table.append(tr);});
}
async function renderAccount(){
 const a=current();if(!a)return;
 const summary=clear("account-summary"),left=el("div"),right=el("div",null,"score-detail");left.append(el("h2",a.name),el("p",a.brand.toUpperCase()+" / "+a.domain+" / owner: "+(a.owner||"unverified"),"subtle"));right.append(el("strong",a.score.fit+" / "+a.score.intent.toFixed(0)),el("div","Fit / intent · "+(a.cohort?.arm||"not assigned")));summary.append(left,right);
 const signals=clear("signals");a.score.signals.forEach(s=>{const n=el("div",null,"signal");n.append(el("strong",s.signal+" · "+s.points.toFixed(1)+" decayed points"),el("small",s.source_key));signals.append(n);});if(!a.score.signals.length)signals.append(el("p","No current qualifying intent.","subtle"));
 if(a.score.reasons.length)signals.append(el("p","Current exclusions: "+a.score.reasons.join(", "),"subtle"));
 $("sources").textContent=pretty(state.sources.filter(s=>s.account_id===a.id).map(s=>({source_key:s.source_key,observed_at:s.observed_at,received_at:s.received_at,disposition:s.disposition,content:JSON.parse(s.payload).data})));
 const action=actionFor(a.id);$("dispatch").disabled=!action;$("approve").disabled=!prepared;$("prepare").disabled=!a.score.eligible||a.cohort?.arm!=="treatment";
 const payload=prepared?.payload||(action?JSON.parse(action.payload):null);
 if(payload){$("prepared").textContent="Owner: "+payload.owner+"\nContact: "+payload.contact+"\nSequence: "+payload.sequence+"\n\n"+payload.message+(prepared?"\n\nAwaiting exact approval.":"\n\nApproved by "+action.reviewer+" · "+action.approved_at);$("exact-payload").textContent=pretty(payload);}
 else {$("prepared").textContent="Prepare a review to inspect the exact proposed owner, sequence and content. Nothing is enrolled until approved and dispatched.";$("exact-payload").textContent="No action prepared.";}
 if(action?.receipt){const receipt=JSON.parse(action.receipt);$("receipt").textContent="INDEPENDENT READ-BACK VERIFIED\n"+receipt.receipt_id+"\nPayload SHA-256: "+receipt.payload_hash;}
 else $("receipt").textContent=action?"Status: "+action.status+" · "+(action.last_error||"No remote effect observed."):"";
 const timeline=clear("timeline");state.outcomes.filter(f=>f.account_id===a.id).sort((x,y)=>x.occurred_at.localeCompare(y.occurred_at)).forEach(f=>{const n=el("div",null,"timeline-item");n.append(el("strong",f.kind.replaceAll("_"," ")+(f.amount_cents?" · "+money(f.amount_cents):"")),el("small",f.occurred_at+" · "+f.origin+" · "+f.business_id));timeline.append(n);});
 try{const id=a.id;const brief=await api("accounts/"+id+"/research");if(selected!==id)return;const n=clear("research");n.append(el("p",brief.summary,"subtle"),el("div",brief.suggested_question,"draft"),el("p",brief.sources.length+" source records · deterministic evidence index · no model inference","subtle"));}catch(e){message(e.message,true);}
}
function renderRoutes(){const r=clear("routes");state.routes.forEach(route=>{const n=el("div",null,"evidence-item");n.append(chip(route.status),el("p",route.reason),el("small",route.owner||"No owner assigned"),el("small",route.source_key),el("small",route.action_key?"Linked action: "+route.action_key:"No approved enrollment linked"));r.append(n);});}
function renderRecovery(){
 $("reconciliation").textContent=pretty(state.reconciliation);$("clock").textContent=state.clock;
 const journal=clear("journal");state.actions.forEach(a=>{const tr=el("tr"),account=state.accounts.find(x=>x.id===a.account_id);let td=el("td");td.append(el("strong",account?.name),el("small",a.action_key));tr.append(td);td=el("td");td.append(chip(a.status));tr.append(td,el("td",a.attempts+" / 3"),el("td",a.last_error||"Exact receipt verified"),el("td",a.receipt?JSON.parse(a.receipt).receipt_id:"—"));journal.append(tr);});
 const audit=clear("audit");[...state.audit].reverse().slice(0,35).forEach(a=>{const n=el("div",null,"audit-row");n.append(el("time",a.at),el("strong",a.event),el("span",a.subject));audit.append(n);});
}
async function load(){state=await api("state");if(!selected)selected=state.actions.find(a=>a.receipt)?.account_id||state.accounts[0].id;for(const id of ["account-select","inbound-account"]){const node=clear(id);state.accounts.forEach(a=>{const option=el("option",a.name+" · "+a.brand);option.value=a.id;node.append(option);});}$("account-select").value=selected;renderOverview();await renderAccount();renderRoutes();renderRecovery();}
$("brand-filter").onchange=renderOverview;$("account-select").onchange=e=>selectAccount(e.target.value);
$("prepare").onclick=()=>task(async()=>{prepared=await api("accounts/"+selected+"/prepare",{});await renderAccount();message("Review prepared. Check the exact owner, sequence and content before approval.");});
$("approve").onclick=()=>task(async()=>{const action=await api("accounts/"+selected+"/approve",{prepared,reviewer:"demo-reviewer"});prepared=null;await load();message("Exact action approved: "+action.action_key+". No enrollment has been sent by approval alone.");});
$("dispatch").onclick=()=>task(async()=>{const action=actionFor(selected);const result=await api("actions/"+action.action_key+"/dispatch",{});await load();message("Delivery observation: "+result.status+(result.reason?" · "+result.reason:" · exact independent receipt verified"),["blocked","exhausted"].includes(result.status));});
document.querySelectorAll("[data-feedback]").forEach(button=>button.onclick=()=>task(async()=>{await api("accounts/"+selected+"/feedback",{kind:button.dataset.feedback});await load();message("Synthetic downstream feedback persisted and independently read back.");}));
$("lost-ack").onclick=()=>task(async()=>{await api("fault",{fault:"lost_ack"});message("Next local enrollment will commit and close the HTTP connection before acknowledging. Existing receipts are unchanged.");});
$("rate-limit").onclick=()=>task(async()=>{await api("fault",{fault:"rate_limit"});message("Next local enrollment request will return 429 without creating an effect.");});
$("optout").onclick=()=>task(async()=>{await api("accounts/"+selected+"/optout",{});prepared=null;await load();message("Synthetic opt-out recorded. New dispatch is denied; historical receipts can still reconcile.");});
$("refresh").onclick=()=>task(async()=>{await load();message("Fresh local state and independent destination receipts read.");});
$("advance").onclick=()=>task(async()=>{const d=new Date(state.clock);d.setSeconds(d.getSeconds()+5);await api("clock",{at:d.toISOString().replace(".000Z","Z")});prepared=null;await load();message("Scenario clock advanced five seconds; current policy will be checked before a new write.");});
$("inbound-form").onsubmit=e=>{e.preventDefault();task(async()=>{const a=state.accounts.find(a=>a.id===$("inbound-account").value);const result=await api("ingest",{version:"source/v1",source:"web",source_id:"interactive-form-"+crypto.randomUUID(),brand:a.brand,kind:"inbound",domain:a.domain,account_id:a.id,observed_at:state.clock,data:{email:"review@"+a.domain,request:$("inbound-request").value,consent:$("inbound-consent").checked}});$("inbound-result").textContent=pretty(result);await load();message("Inbound decision persisted: "+result.status+" · "+result.reason);});};
task(async()=>{await load();message("Executed synthetic scenario · actual local HTTP effects · no native vendor execution or commercial uplift claimed.");});

let recordedAI;
function renderRecordedCase(){
 const r=recordedAI.records[Number($("ai-case").value)];
 $("ai-case-status").textContent=r.case_id+" · seed "+r.seed+" · "+(r.validation_error||"Exact quotations checked")+" · "+r.latency_seconds+"s";
 $("ai-response").textContent=r.raw_response;
 $("ai-policy").textContent=pretty(r.policy);
 $("ai-context").textContent=pretty({context:r.context,citations:r.parsed?.citations,context_hash:r.context_hash,request_hash:r.request_hash,usage:r.usage,semantic_support:r.semantic_support});
}
async function loadRecordedEvidence(){
 const [native,ai]=await Promise.all([api("evidence/salesforce"),api("evidence/ai")]);
 const n=clear("native-proof");$("native-status").textContent=native.status||"Unavailable";
 if(native.status==="passed"){
  [["Environment",native.preflight.organization_type],["Authenticated requests",native.authenticated_requests],["Independent exact readback","Verified"],["Lost acknowledgement / duplicates","Recovered / rejected"],["New review cleanup",native.cleanup.new_review_status+" · retained audit record"]].forEach(([k,v])=>{const row=el("div",null,"assurance-item");row.append(el("span",k),el("b",v));n.append(row);});
  n.append(el("p","Standard Account / Contact / Task access was unavailable. Existing permissions were preserved.","subtle"));
 }else n.append(el("p","No successful native record is available in this checkout.","subtle"));
 $("native-detail").textContent=pretty(native);
 const a=clear("ai-proof");$("ai-status").textContent=ai.inferences_executed?ai.inferences_executed+" RESPONSES":"Unavailable";
 if(ai.records){recordedAI=ai;
  [["Executed model",ai.runtime.model],["Evaluation cases",new Set(ai.records.map(r=>r.case_id)).size],["Exact citation checks",ai.exact_citation_checks_passed+" / "+ai.inferences_executed],["Executable model prose","Never authorized"]].forEach(([k,v])=>{const row=el("div",null,"assurance-item");row.append(el("span",k),el("b",v));a.append(row);});
  ai.records.forEach((r,i)=>{const option=el("option",r.case_id.replaceAll("_"," ")+" · seed "+r.seed);option.value=i;$("ai-case").append(option);});
  $("ai-case").onchange=renderRecordedCase;renderRecordedCase();
 }else a.append(el("p","No actual model responses are available in this checkout.","subtle"));
}
task(loadRecordedEvidence);
