# Held-out questions (headline: never used for tuning)

## Overall

| Config | Accuracy | Correct | Abstained | Contradicted | Evidence recall | $/question | p50 s | p95 s | Model calls | Errors |
|---|---|---|---|---|---|---|---|---|---|---|
| naive | 76% | 65% | 12% | 0% | 68% | $0.0062 | 3.5 | 6.4 | 1.0 | 0 |
| full | 84% | 69% | 0% | 0% | 77% | $0.0093 | 18.8 | 33.7 | 5.3 | 0 |
| no_router | 88% | 75% | 0% | 0% | 77% | $0.0142 | 25.1 | 57.6 | 6.0 | 0 |
| no_grading | 85% | 71% | 0% | 0% | 76% | $0.0085 | 15.4 | 26.5 | 4.4 | 0 |
| rerank_only | 86% | 73% | 0% | 0% | 77% | $0.0077 | 15.9 | 31.3 | 4.5 | 0 |
| no_sufficiency | 92% | 83% | 0% | 0% | 79% | $0.0115 | 21.1 | 34.3 | 5.3 | 0 |
| no_verify | 86% | 73% | 0% | 0% | 76% | $0.0074 | 15.3 | 29.9 | 4.1 | 0 |
| low_effort | 86% | 73% | 0% | 0% | 78% | $0.0079 | 15.8 | 27.4 | 5.1 | 0 |

## Accuracy by question category

| Config | call_graph | conceptual | existence | history | identifier | lookup |
|---|---|---|---|---|---|---|
| naive | 100% | 94% | 62% | 62% | 50% | 88% |
| full | 88% | 81% | 88% | 94% | 81% | 75% |
| no_router | 88% | 88% | 88% | 94% | 88% | 81% |
| no_grading | 88% | 81% | 94% | 94% | 75% | 81% |
| rerank_only | 88% | 81% | 94% | 94% | 81% | 81% |
| no_sufficiency | 100% | 81% | 94% | 94% | 100% | 81% |
| no_verify | 88% | 81% | 94% | 94% | 81% | 81% |
| low_effort | 88% | 75% | 94% | 94% | 88% | 81% |

Total spend (answers + judge): $4.02

# Dev questions (used while building; optimistic)

## Overall

| Config | Accuracy | Correct | Abstained | Contradicted | Evidence recall | $/question | p50 s | p95 s | Model calls | Errors |
|---|---|---|---|---|---|---|---|---|---|---|
| naive | 69% | 58% | 16% | 3% | 47% | $0.0045 | 4.6 | 9.9 | 1.0 | 0 |
| full | 95% | 90% | 0% | 0% | 78% | $0.0130 | 25.2 | 54.9 | 5.6 | 0 |
| no_router | 98% | 97% | 0% | 0% | 78% | $0.0157 | 28.8 | 51.0 | 5.8 | 0 |
| no_grading | 90% | 81% | 0% | 0% | 74% | $0.0121 | 23.2 | 41.8 | 4.9 | 0 |
| rerank_only | 92% | 84% | 0% | 0% | 82% | $0.0122 | 22.3 | 48.8 | 4.7 | 0 |
| no_sufficiency | 98% | 97% | 0% | 0% | 78% | $0.0151 | 23.8 | 48.5 | 5.6 | 0 |
| no_verify | 94% | 87% | 0% | 0% | 80% | $0.0091 | 20.4 | 31.6 | 4.3 | 0 |
| low_effort | 94% | 87% | 0% | 0% | 78% | $0.0124 | 19.4 | 45.5 | 5.6 | 0 |

## Accuracy by question category

| Config | call_graph | conceptual | existence | history | identifier | lookup |
|---|---|---|---|---|---|---|
| naive | 60% | 80% | 58% | 30% | 90% | 100% |
| full | 90% | 100% | 92% | 100% | 90% | 100% |
| no_router | 100% | 90% | 100% | 100% | 100% | 100% |
| no_grading | 90% | 90% | 92% | 100% | 80% | 90% |
| rerank_only | 90% | 100% | 92% | 100% | 70% | 100% |
| no_sufficiency | 90% | 100% | 100% | 100% | 100% | 100% |
| no_verify | 90% | 100% | 92% | 100% | 90% | 90% |
| low_effort | 90% | 100% | 92% | 100% | 90% | 90% |

Total spend (answers + judge): $3.31

# All questions

## Overall

| Config | Accuracy | Correct | Abstained | Contradicted | Evidence recall | $/question | p50 s | p95 s | Model calls | Errors |
|---|---|---|---|---|---|---|---|---|---|---|
| naive | 73% | 62% | 14% | 1% | 60% | $0.0056 | 3.6 | 9.4 | 1.0 | 0 |
| full | 89% | 77% | 0% | 0% | 78% | $0.0108 | 20.5 | 41.7 | 5.4 | 0 |
| no_router | 92% | 84% | 0% | 0% | 78% | $0.0148 | 25.5 | 54.1 | 5.9 | 0 |
| no_grading | 87% | 75% | 0% | 0% | 75% | $0.0099 | 17.7 | 32.3 | 4.6 | 0 |
| rerank_only | 89% | 77% | 0% | 0% | 79% | $0.0095 | 17.9 | 35.5 | 4.6 | 0 |
| no_sufficiency | 94% | 89% | 0% | 0% | 79% | $0.0129 | 22.8 | 41.7 | 5.5 | 0 |
| no_verify | 89% | 78% | 0% | 0% | 78% | $0.0081 | 16.5 | 31.6 | 4.2 | 0 |
| low_effort | 89% | 78% | 0% | 0% | 78% | $0.0097 | 17.5 | 33.3 | 5.3 | 0 |

## Accuracy by question category

| Config | call_graph | conceptual | existence | history | identifier | lookup |
|---|---|---|---|---|---|---|
| naive | 85% | 88% | 61% | 50% | 65% | 92% |
| full | 88% | 88% | 89% | 96% | 85% | 85% |
| no_router | 92% | 88% | 93% | 96% | 92% | 88% |
| no_grading | 88% | 85% | 93% | 96% | 77% | 85% |
| rerank_only | 88% | 88% | 93% | 96% | 77% | 88% |
| no_sufficiency | 96% | 88% | 96% | 96% | 100% | 88% |
| no_verify | 88% | 88% | 93% | 96% | 85% | 85% |
| low_effort | 88% | 85% | 93% | 96% | 88% | 85% |

Total spend (answers + judge): $7.33
