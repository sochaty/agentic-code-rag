## Overall

| Config | Accuracy | Correct | Abstained | Contradicted | Evidence recall | $/question | p50 s | p95 s | Model calls | Errors |
|---|---|---|---|---|---|---|---|---|---|---|
| naive | 69% | 58% | 16% | 3% | 46% | $0.0072 | 4.2 | 8.6 | 1.0 | 0 |
| full | 92% | 84% | 0% | 0% | 80% | $0.0121 | 26.7 | 55.9 | 5.5 | 0 |

## Accuracy by question category

| Config | call_graph | conceptual | existence | history | identifier | lookup |
|---|---|---|---|---|---|---|
| naive | 60% | 80% | 58% | 30% | 90% | 100% |
| full | 90% | 90% | 92% | 90% | 90% | 100% |

Total spend (answers + judge): $0.70
