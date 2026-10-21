-- Grain: one assigned account. Denominator never becomes number of contacts or touches.
-- Aggregate each outcome type before joining. Outcome and knowledge cutoffs both apply.
WITH eligible_outcomes AS (
 SELECT f.*, c.experiment FROM feedback f JOIN cohorts c ON c.account_id=f.account_id
 WHERE c.experiment=:experiment AND f.occurred_at >= c.assigned_at AND f.occurred_at < c.window_end
   AND f.occurred_at <= :as_of AND f.received_at <= :as_of
   AND f.created_at >= c.assigned_at
   AND (:currency IS NULL OR (SELECT json_extract(s.payload,'$.data.currency')
                             FROM sources s WHERE s.source_key=f.source_key)=:currency)
), meetings AS (
 SELECT experiment,account_id,count(DISTINCT business_id) meetings FROM eligible_outcomes
 WHERE kind='meeting_qualified' GROUP BY experiment,account_id
), opportunities AS (
 SELECT experiment,account_id,count(DISTINCT business_id) opportunities,sum(amount_cents) pipeline_cents
 FROM eligible_outcomes WHERE kind='opportunity_accepted' GROUP BY experiment,account_id
), exposures AS (
 SELECT experiment,account_id,count(*) exposures FROM actions
 WHERE receipt IS NOT NULL AND json_extract(receipt,'$.accepted_at')<=:as_of
 GROUP BY experiment,account_id
)
SELECT c.*, :currency currency, CASE WHEN c.window_end<=:as_of THEN 1 ELSE 0 END mature,
 coalesce(m.meetings,0) meetings,coalesce(o.opportunities,0) opportunities,
 coalesce(o.pipeline_cents,0) pipeline_cents,coalesce(x.exposures,0) exposures
FROM cohorts c LEFT JOIN meetings m ON c.experiment=m.experiment AND c.account_id=m.account_id
LEFT JOIN opportunities o ON c.experiment=o.experiment AND c.account_id=o.account_id
LEFT JOIN exposures x ON c.experiment=x.experiment AND c.account_id=x.account_id
WHERE c.experiment=:experiment AND c.assigned_at<=:as_of ORDER BY c.account_id;
