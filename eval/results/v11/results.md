# Fresh questions (written after v1.1; never used for tuning)

## Overall

| Config | Accuracy | Correct | Abstained | Contradicted | Evidence recall | $/question | p50 s | p95 s | Model calls | Errors |
|---|---|---|---|---|---|---|---|---|---|---|
| naive | 58% | 43% | 23% | 10% | 46% | $0.0064 | 4.0 | 6.5 | 1.0 | 0 |
| full | 88% | 80% | 3% | 0% | 73% | $0.0137 | 20.4 | 35.1 | 4.6 | 0 |
| no_follow_up | 85% | 73% | 3% | 0% | 78% | $0.0108 | 21.9 | 35.9 | 4.9 | 0 |

## Accuracy by question category

| Config | call_graph | conceptual | existence | history | identifier | lookup |
|---|---|---|---|---|---|---|
| naive | 60% | 50% | 40% | 60% | 50% | 90% |
| full | 90% | 60% | 80% | 100% | 100% | 100% |
| no_follow_up | 70% | 50% | 90% | 100% | 100% | 100% |

Total spend (answers + judge): $1.07
