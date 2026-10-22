"use strict";
let researchCatalog, researchAccount, researchRun, researchAssessment;
function researchFacts(container, heading, items){container.append(el("h3",heading));if(!items.length)container.append(el("p","None proposed.","subtle"));items.forEach(item=>{const card=el("div",null,"research-fact");card.append(el("strong",item.text),el("p",item.quote||item.rationale,"subtle"),el("small",item.source_id||item.source_ids.join(" · ")));container.append(card);});}
function showResearch(id){
 researchAccount=researchCatalog.accounts.find(a=>a.id===id)||researchCatalog.evaluation_cases.find(a=>a.id===id);
 const a=researchAccount,c=a.context,p=a.priority;
 $("research-account-name").textContent=c.name;$("research-domain").textContent=c.domain+" · SYNTHETIC ACCOUNT · source clock "+c.as_of;
 $("research-owner").textContent="CRM owner: "+(p.owner||"unverified")+" · "+(p.eligible?"Eligible for local internal review":p.blocks.join(" · "));
 clear("research-score").append(metric("ICP fit",p.fit+" / 100","Separate from intent"),metric("Signal contribution",p.signal_points,"Freshness × confidence × category"),metric("Research priority",p.priority,"Not a purchase probability"),metric("Current authority",p.eligible?"Reviewable":"Suppressed","Rechecked at approval"));
 const sources=clear("research-sources");c.sources.forEach(s=>{const contribution=p.contributions.find(x=>x.source_id===s.source_id),card=el("article",null,"research-fact");card.append(chip(s.kind),el("p",s.text),el("small",s.source_id+" · "+contribution.reason+" · "+contribution.points+" points · published "+(s.published_at||"unknown")));sources.append(card);});
 $("research-enrichment").textContent=pretty(a.enrichment);$("research-context").textContent=pretty({context:c,research_priority:p});
 const options=clear("research-approach");a.runs.forEach(run=>{const o=el("option",run.record.approach+(run.record.operator_execution?" · new operator execution":""));o.value=run.run_hash;options.append(o);});
 options.value=[...a.runs].reverse().find(r=>r.record.approach==="evidence-first-v3")?.run_hash||a.runs[0]?.run_hash;
 showResearchRun();
}
function showResearchRun(){
 const a=researchAccount;researchRun=a.runs.find(r=>r.run_hash===$("research-approach").value);if(!researchRun)return;
 const r=researchRun.record,b=r.parsed,content=clear("research-brief");
 if(b){researchFacts(content,"Observed facts",b.facts);researchFacts(content,"Possible implications · hypotheses",b.hypotheses);content.append(el("h3","Why it matters"),el("p",b.relevance),el("h3","Gaps & contradictions"));const gaps=el("ul");b.gaps.forEach(g=>gaps.append(el("li",g)));content.append(gaps);}
 else content.append(el("p","Response rejected: "+r.error,"notice error"));
 const savedReview=a.reviews.find(v=>v.run_hash===researchRun.run_hash);
 $("research-opening").value=savedReview?savedReview.opening:(b?.opening||"");$("research-opening").disabled=!!savedReview||!b||b.action==="abstain";
 $("research-approve").disabled=!researchRun.source_snapshot_current||!a.priority.eligible||!b||b.action!=="review"||a.reviews.some(v=>v.run_hash===researchRun.run_hash);
 $("research-dismiss").disabled=a.reviews.some(v=>v.run_hash===researchRun.run_hash);
 $("research-run-status").textContent="Actual Qwen3 response · "+r.latency_seconds+" seconds · "+(r.usage?.completion_tokens||0)+" output tokens · "+(b?.action||"rejected")+(researchRun.source_snapshot_current?"":" · SOURCES CHANGED: rerun research before approval");
 const assessment=researchAssessment?.records.find(x=>x.run_hash===researchRun.run_hash);$("research-selected-assessment").textContent=assessment?assessment.seller_usefulness+": "+assessment.note:"Exact source quotation checks do not establish factual entailment or seller usefulness.";
 $("research-raw").textContent=r.raw_response||"No response recorded.";$("research-request").textContent=pretty({request:r.request,context_hash:r.context_hash,request_hash:r.request_hash,runtime:r.runtime,contract_assessment:r.contract_assessment});
 $("research-decisions").textContent=a.reviews.length?pretty(a.reviews):"No seller decision recorded in this workspace. Approval stores an exact local review; it cannot send a message or create a Salesforce Task.";
}
async function loadResearch(){
 researchCatalog=await api("research");const m=researchCatalog.metrics;
 if(!researchCatalog.accounts.length){$("research-run-status").textContent="Research evidence unavailable in this package.";return;}
 clear("research-metrics").append(metric("Accounts researched",m.accounts_researched,"Actual recorded local inference"),metric("Time per candidate",m.seconds_per_usable_run?.toFixed(1)+"s","Schema-valid review candidates; utility separate"),metric("Local seller decisions",m.seller_decisions.reduce((n,r)=>n+r.count,0),"Persisted approve / dismiss"),metric("API spend","$0","Local GPU energy not metered"));
 const list=clear("research-list");researchCatalog.accounts.forEach(a=>{const button=el("button",null,"research-account");button.type="button";button.dataset.researchAccount=a.id;button.append(el("strong",a.context.name),el("span",a.context.domain),el("small","Priority "+a.priority.priority+" · "+(a.priority.eligible?"local review":"suppressed")));button.onclick=()=>showResearch(a.id);list.append(button);});
 const cases=clear("research-case");researchCatalog.evaluation_cases.forEach(a=>{const option=el("option",a.id);option.value=a.id;cases.append(option);});cases.onchange=()=>showResearch(cases.value);
 $("research-comparison").textContent=pretty(researchCatalog.comparisons);$("research-sql-metrics").textContent=pretty(m);
 $("research-approach").onchange=showResearchRun;
 showResearch(researchAccount?.id||researchCatalog.accounts[0].id);
}
for(const decision of ["approve","dismiss"])$("research-"+decision).onclick=()=>task(async()=>{const result=await api("research/review",{run_hash:researchRun.run_hash,opening:$("research-opening").value,decision,context_hash:researchAccount.context_hash});message("Local seller decision recorded. No Salesforce write or communication authorized. Review "+result.review_hash.slice(0,12));await loadResearch();});
task(async()=>{researchAssessment=await api("evidence/research-assessment");await loadResearch();const source=await api("evidence/public-jobs");$("research-public-source").textContent=pretty(source);$("research-assessment").textContent=pretty(researchAssessment);});
