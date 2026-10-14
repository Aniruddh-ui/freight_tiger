# Evaluation report

Results file: output/llm_groq/results.csv

## 1. Labeled cases: 12/12 pass

| result | route | week_of | expected | got | source |
|---|---|---|---|---|---|
| PASS | Delhi-Jaipur | 2024-11-11 | Yes  | Yes  | sample |
| PASS | Ahmedabad-Mumbai | 2025-01-20 | No (justified) N002 | No (justified) N002 | sample |
| PASS | Mumbai-Pune | 2025-09-15 | Yes  | Yes  | sample |
| PASS | Chennai-Bangalore | 2025-02-24 | No (justified) N001 | No (justified) N001 | hand |
| PASS | Chennai-Bangalore | 2025-03-03 | No (justified) N001 | No (justified) N001 | hand |
| PASS | Chennai-Bangalore | 2025-03-10 | Yes  | Yes  | hand |
| PASS | Chennai-Bangalore | 2025-03-17 | Yes  | Yes  | hand |
| PASS | Delhi-Jaipur | 2024-11-18 | Yes  | Yes  | hand |
| PASS | Mumbai-Delhi | 2024-07-29 | No  | No  | hand |
| PASS | Delhi-Chennai | 2025-05-05 | No  | No  | hand |
| PASS | Ahmedabad-Mumbai | 2025-01-27 | No  | No  | hand |
| PASS | Mumbai-Pune | 2025-12-22 | Yes  | Yes  | hand |

## 2. Independent recomputation: 728/728 rows match

Missing/extra rows: 0. Mismatches: none

## 3. Grounding audit: 3 justified rows, 0 problems


## 4. Threshold sensitivity (anomalies flagged before note check)

| own-history | peers | weeks flagged | labeled anomalies caught | labeled normals flagged |
|---|---|---|---|---|
| 10% | 15% | 28 | 9/9 | 0/3 |
| 10% | 20% | 21 | 9/9 | 0/3 |
| 10% | 25% | 14 | 8/9 | 0/3 |
| 15% | 15% | 27 | 9/9 | 0/3 |
| 15% | 20% | 20 | 9/9 | 0/3 | (chosen)
| 15% | 25% | 13 | 8/9 | 0/3 |
| 20% | 15% | 27 | 9/9 | 0/3 |
| 20% | 20% | 20 | 9/9 | 0/3 |
| 20% | 25% | 13 | 8/9 | 0/3 |
