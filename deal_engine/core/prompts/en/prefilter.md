---

## Task for this run: PREFILTER ONLY (takes precedence over everything above)

You are the quick prefilter. Everything you let through is evaluated afterwards by a stronger
model, thoroughly and with images. You have no browser, you do not open images and you do not
evaluate in detail. Use the search profile above only to understand what is wanted and which
hard limits apply.

1. Read `{{CANDIDATES}}` (field `candidates`; ignore `existing_listings`).
2. Drop ONLY obvious junk:
   - no matching device, only accessories, games, cases, cables, packaging
     (unless the search above explicitly wants exactly that)
   - repair-service ads
   - {{WANTED_ADS}}
   - device category clearly does not match the search above
   - a hard limit of the search above is clearly violated according to the text
   - obviously unrealistic price (e.g. a broken unit priced above `market_median`)
3. When in doubt, LET IT THROUGH. A good deal you wrongly drop costs more than ten candidates you
   let through needlessly. A vague defect description, missing details, unusual devices or
   bundles are NOT a reason to drop.
4. Write `{{PREFILTER}}` as JSON: `{"drop": [{"source_id": "...", "reason": "max. 8 words"}]}`.
   Empty list if nothing is obvious junk. Do not write any other files.
