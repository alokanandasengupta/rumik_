# Schema design — IRA Rumik Synthetic Product Analytics (6mo, 50K users)

Workbook: `IRA_Rumik_Synthetic_Product_Analytics_6mo_50K_pricing_aligned.xlsx`
16 sheets total: 3 README sheets (data dictionary, known issues, gap-fix log) + 13 data tables.
This is a synthetic dataset for a companionship-app-style product, covering ~50K users over 26 weeks, with product analytics, subscription billing, marketing/creative performance, incrementality testing, support, and happiness-tracking tables.

---

## 1. Table inventory

| Table | Grain / key | Rows | Cols | Role |
|---|---|---|---|---|
| `dim_users` | 1 row per `user_id` | 50,000 | 25 | User dimension (acquisition, targeting, current sub state) |
| `fact_events` | 1 row per `event_id` | 721,270 | 28 | Raw event-level log (all product + billing events) |
| `fact_payments` | 1 row per `event_id` | 18,278 | 28 | **Mirror subset** of `fact_events` filtered to payment-bearing events (not an independent ledger) |
| `subscription_lifecycle` | 1 row per `lifecycle_id` | 6,498 | 11 | Trustworthy subscription state-transition ledger |
| `experiment_rollout_calendar` | 1 row per date range × experiment | 48 | 5 | Weekly pricing-experiment exposure shares |
| `marketing_spend_weekly` | 1 row per `week_start` × `channel` × `campaign` | 338 | 11 | Weekly spend/performance by channel & campaign |
| `creative_performance_weekly` | 1 row per `week_start` × `ad_id` | 2,080 | 17 | Ad-level weekly creative performance |
| `ad_dayparting_hourly` | 1 row per `ad_id` × `hour_of_day` | 960 | 10 | Ad-level hourly performance curve (0–23h) |
| `incrementality_test_log` | 1 row per `test_id` | 22 | 15 | Holdout/control marketing test (weeks 20–21) |
| `audience_overlap_estimates` | 1 row per `campaign` | 11 | 6 | Cannibalization / overlap estimates per campaign |
| `nudge_log` | 1 row per `nudge_id` | 83,948 | 7 | Push/WhatsApp/email nudge sends |
| `support_tickets` | 1 row per `ticket_id` | 889 | 19 | Support tickets |
| `user_happiness_snapshots` | 1 row per `happiness_id` | 71,346 | 6 | Periodic per-user happiness score (~10-day cadence) |

---

## 2. Entity-relationship diagram

See the rendered ERD above. Summary of real (joinable) relationships:

- `dim_users.user_id` (PK) → fans out to `fact_events.user_id`, `subscription_lifecycle.user_id`, `nudge_log.user_id`, `support_tickets.linked_user_id`, `user_happiness_snapshots.user_id`
- `fact_events.event_id` (PK) — `fact_payments` is a **filtered mirror** of this table (same `event_id`s, same columns), not a separate ledger
- `marketing_spend_weekly` (`week_start`+`channel`+`campaign`) → `creative_performance_weekly` (`channel`+`campaign`, further split by `ad_id`) → `ad_dayparting_hourly` (`ad_id`)
- `marketing_spend_weekly` (`channel`+`campaign`) → `incrementality_test_log` and `audience_overlap_estimates` (`channel`+`campaign`)
- `dim_users.ad_set_id` / `dim_users.ad_id` softly link a user to the ad that acquired them, joinable against `creative_performance_weekly` and `ad_dayparting_hourly`
- `dim_users.active_experiment` / `active_experiment_group` softly link to `experiment_rollout_calendar.active_experiment` (calendar defines exposure shares by date range, not a row-level FK)
- `nudge_log.user_id` also carries `nudge_experiment_arm` context that lives on `dim_users`
- `support_tickets.source_event_hint` and `subscription_lifecycle.order_id` / `fact_events.order_id` are loose cross-references, not enforced keys

---

## 3. Column-level detail

### `dim_users` — PK: `user_id`
| Column | Type | Notes |
|---|---|---|
| user_id | string | Primary key |
| distinct_id | string | Pre-login analytics identity |
| signup_ts | datetime | |
| platform | string | iOS / Android / Web |
| country_code | string | |
| pricing_region_at_signup | string | Region at time of signup |
| pricing_region_current | string | Can drift from signup region (~1.5% of users) |
| creation_source | string | |
| active_experiment | string | Pricing experiment name, joins conceptually to `experiment_rollout_calendar` |
| active_experiment_group | string | Treatment/control arm |
| nudge_experiment_arm | string | Nudge-timing A/B arm, live from week 18 |
| media_source | string | |
| campaign | string | Joins to marketing tables |
| channel | string | Joins to marketing tables |
| ad_set_id | string | Joins to `creative_performance_weekly` / `ad_dayparting_hourly` |
| ad_id | string | Joins to `creative_performance_weekly` / `ad_dayparting_hourly` |
| device_model | string | |
| os_version | string | |
| ad_intent | string | |
| targeting_age_bucket | string | |
| targeting_gender | string | |
| targeting_interest | string | |
| is_paid_user_current | bool | |
| subscription_tier_current | string | |
| has_active_sub_current | bool | |

### `fact_events` — PK: `event_id`
| Column | Type | Notes |
|---|---|---|
| event_id | string | Primary key |
| event_ts | datetime | |
| user_id | string | FK → `dim_users.user_id` |
| distinct_id | string | |
| session_id | string | |
| event_name | string | Includes `App Opened` (login/session-start); subscription completion appears under 3 inconsistent names: `Subscription Purchase Completed`, `Subscription Purchased`, `purchase` |
| platform | string | |
| pricing_region_at_signup | string | |
| pricing_region_current | string | |
| active_experiment | string | |
| creation_source | string | |
| event_source | string | |
| paywall_surface | string | |
| product_type | string | |
| product_id | float | |
| raw_plan_tier | float | |
| raw_pack_name | string | |
| raw_pack_type | string | |
| amount_inr | float | Credit-pack pricing realigned: small 149→19, medium 399→39, large 899→79 |
| credits | float | |
| payment_id | string | |
| order_id | string | |
| error | float | |
| message_length_chars | float | |
| message_content_category | string | Structured category tag, not free text; directionally biased near conversion/ghosting |
| voice_call_seconds | float | |
| remaining_balance | float | |
| insert_id | string | ~0.06% of events have duplicate `insert_id` pairs (SDK double-fire) |

### `fact_payments` — same 28 columns as `fact_events`, key: `event_id`
Filtered subset restricted to payment-bearing events. **Known issue: not an independent ledger** — cannot be used to cross-validate `fact_events` revenue. Several numeric columns (`product_id`, `raw_plan_tier`, `error`) read as string/object here versus float in `fact_events` due to sparser, mixed values.

### `subscription_lifecycle` — PK: `lifecycle_id`
| Column | Type | Notes |
|---|---|---|
| lifecycle_id | string | Primary key |
| event_ts | datetime | |
| user_id | string | FK → `dim_users.user_id` |
| event_name | string | State-transition event |
| product_id | string | |
| raw_plan_tier | string | |
| amount_inr | int | Populated directly (trustworthy revenue figure) |
| source | string | |
| status_before | string | |
| status_after | string | |
| order_id | string | Loose cross-reference to `fact_events.order_id` |

### `experiment_rollout_calendar` — key: `start_date` + `end_date` + `active_experiment`
| Column | Type | Notes |
|---|---|---|
| start_date | datetime | |
| end_date | datetime | |
| active_experiment | string | |
| exposure_share | float | |
| notes | string | Rollout (Jan–Apr) is sequential/collinear with calendar time by design; weeks 17–26 are the cleaner read |

### `marketing_spend_weekly` — key: `week_start` + `channel` + `campaign`
| Column | Type | Notes |
|---|---|---|
| week_start | datetime | |
| channel | string | |
| campaign | string | |
| spend_inr | int | |
| impressions | float | |
| clicks | float | |
| mmp_reported_installs | int | Organic App Store installs can exceed true signups |
| mmp_attributed_signups_7d | int | |
| reported_paid_conversions_14d | int | Undercounts true paid conversions by ~45–70%, worse after week-14 attribution change |
| attribution_model_version | string | `v1_last_click` → `v2_data_driven` at week 14 |
| notes | string | Weeks 20–21 contain an embedded incrementality holdout on ~40% of paid campaigns |

### `creative_performance_weekly` — key: `week_start` + `ad_id`
| Column | Type | Notes |
|---|---|---|
| week_start | datetime | |
| channel | string | |
| campaign | string | FK-ish → `marketing_spend_weekly` |
| ad_set_id | string | |
| ad_id | string | |
| creative_theme | string | |
| placement | string | |
| spend_inr_allocated | int | Allocated, not independently metered |
| impressions | int | |
| reach | int | |
| frequency | float | |
| clicks | int | |
| hook_rate_pct | float | |
| hold_rate_pct | float | |
| ftir_pct | float | |
| cpmr_inr | float | |
| fatigue_status | string | |

### `ad_dayparting_hourly` — key: `ad_id` + `hour_of_day`
| Column | Type | Notes |
|---|---|---|
| channel | string | |
| campaign | string | |
| ad_set_id | string | |
| ad_id | string | |
| hour_of_day | int | 0–23 |
| impressions_share_pct | float | |
| performance_index | float | 100 = average hour; peaks 19:00–22:00 |
| ctr_pct | float | |
| cvr_pct | float | |
| avg_cpc_inr | int | |

### `incrementality_test_log` — PK: `test_id`
| Column | Type | Notes |
|---|---|---|
| test_id | string | Primary key |
| channel | string | |
| campaign | string | FK-ish → `marketing_spend_weekly` |
| test_start | datetime | |
| test_end | datetime | Weeks 20–21 only, ~40% of paid campaigns |
| group | string | test/control |
| incrementality_rate_assumed | float | |
| spend_control_would_be_inr | int | |
| spend_test_actual_inr | int | Cut to 30% of normal during test |
| conversions_control_baseline | int | |
| conversions_test_observed | int | |
| incremental_spend_inr | int | |
| incremental_conversions | int | |
| marginal_cac_inr | float | Consistently higher than `avg_cac_inr` (cannibalization) |
| avg_cac_inr | float | |

### `audience_overlap_estimates` — key: `campaign`
| Column | Type | Notes |
|---|---|---|
| channel | string | |
| campaign | string | |
| overlap_with_organic_pct | float | |
| overlap_with_other_paid_pct | float | |
| estimated_cannibalization_rate_pct | int | |
| basis | string | "empirical" for campaigns in the holdout test, "modeled" otherwise |

### `nudge_log` — PK: `nudge_id`
| Column | Type | Notes |
|---|---|---|
| nudge_id | string | Primary key |
| sent_ts | datetime | |
| user_id | string | FK → `dim_users.user_id` |
| nudge_type | string | Push / WhatsApp / email |
| timing | string | Pre- vs post-first-chat |
| responded_flag | bool | |
| response_ts | datetime | |

### `support_tickets` — PK: `ticket_id`
| Column | Type | Notes |
|---|---|---|
| ticket_id | string | Primary key |
| opened_at | datetime | |
| source_channel | string | |
| linked_user_id | string | FK → `dim_users.user_id` |
| linked_distinct_id | string | |
| ticket_category_l1 | string | |
| ticket_category_l2 | string | |
| priority | string | |
| status | string | |
| first_response_minutes | int | |
| resolution_minutes | float | |
| csat_score | float | |
| refund_requested | bool | |
| refund_amount_inr | float | |
| experiment_at_open | string | |
| platform | string | |
| pricing_region_current | string | |
| source_event_hint | string | Loose reference back to `fact_events` |
| duplicate_of_ticket_id | string | Self-referencing, points to another `ticket_id` |

### `user_happiness_snapshots` — PK: `happiness_id`
| Column | Type | Notes |
|---|---|---|
| happiness_id | string | Primary key |
| user_id | string | FK → `dim_users.user_id` |
| snapshot_ts | datetime | ~10-day cadence |
| happiness_score | float | 0–100 |
| score_trend | float | |
| primary_driver | string | |

---

## 4. Known data-quality issues (carried over from the workbook's README)

- `fact_payments` is a mirror of `fact_events` — no independent payment ledger; can't cross-validate revenue between the two.
- `fact_events` has duplicate `insert_id` pairs (~0.06%) from simulated SDK double-fires.
- Subscription completion is logged under three different `event_name` values for the same business event.
- The pricing experiment rollout is collinear with calendar time through week 16 — weeks 17–26 are the cleaner analytical window.
- `reported_paid_conversions_14d` undercounts true paid conversions by ~45–70%, worsening after the week-14 attribution model change (`v1_last_click` → `v2_data_driven`).
- `mmp_reported_installs` for Organic App Store can exceed actual organic signups.
- `pricing_region_current` differs from `pricing_region_at_signup` for ~1.5% of users (region drift).
- ~0.15% of activated users purchase before ever sending a first message.
- `message_content_category` is a structured tag (directionally biased near conversion/ghosting), not literal conversation text.
- `creative_performance_weekly` and `ad_dayparting_hourly` spend/impression shares are allocated by construction, not independently metered.
- The incrementality test covers only 2 of 26 weeks and ~40% of paid campaigns; `marginal_cac_inr` and `audience_overlap_estimates` outside that scope are modeled/calibrated, not measured — see the `basis` and `group` columns.
- Credit-pack pricing in `fact_events`/`fact_payments` was realigned on 2026-07-10: small 149→19, medium 399→39, large 899→79 (INR).
