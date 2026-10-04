# PyVRP vs Rasad's GA + ACO

15 problems: 5 scenarios x 3 random seeds, on the seeded synthetic sector. Cost is Rasad's own (lower is better), applied to every method's plan. See the top of `pyvrp_vs_ga.py` for how the problem is given to PyVRP.

| Method | Mean cost | Best on (of N) | Plans with a hard-limit penalty |
|---|---:|---:|---:|
| rules | 22.13 | 0 | 0 |
| GA+ACO | 16.36 | 6 | 0 |
| PyVRP | 382.96 | 5 | 9 |
| PyVRP cap | 19.98 | 0 | 0 |
| PyVRP+GA | 15.62 | 15 | 0 |

Run time per problem: GA+ACO about 0.3 s (including the rules), PyVRP 3 s (its time budget).

| Scenario | Seed | Lots | rules | GA+ACO | PyVRP | PyVRP cap | PyVRP+GA |
|---|---:|---:|---:|---:|---:|---:|---:|
| Today, as forecast | 0 | 10 | 16.7 | 12.0 | 12.0 | 17.4 | 12.0 |
| Today, as forecast | 1 | 10 | 16.7 | 13.0 | 12.0 | 17.4 | 11.7 |
| Today, as forecast | 2 | 10 | 16.7 | 12.5 | 12.0 | 17.4 | 12.0 |
| Tangla La closes | 0 | 10 | 17.1 | 11.8 | 11.8 | 17.4 | 11.8 |
| Tangla La closes | 1 | 10 | 17.7 | 12.3 | 12.3 | 17.9 | 12.3 |
| Tangla La closes | 2 | 10 | 17.1 | 12.9 | 11.8 | 17.4 | 11.8 |
| Both passes close | 0 | 10 | 24.1 | 16.4 | 703.1* | 17.4 | 15.1 |
| Both passes close | 1 | 10 | 24.6 | 16.8 | 708.7* | 17.9 | 15.6 |
| Both passes close | 2 | 10 | 24.1 | 16.4 | 703.1* | 17.4 | 15.1 |
| Passes shut, helicopters grounded | 0 | 11 | 31.8 | 26.2 | 713.2* | 26.2 | 25.1 |
| Passes shut, helicopters grounded | 1 | 11 | 32.3 | 26.7 | 718.7* | 26.7 | 25.6 |
| Passes shut, helicopters grounded | 2 | 11 | 31.8 | 25.1 | 713.2* | 26.2 | 25.1 |
| Troop surge at Kesari (+60%) | 0 | 12 | 20.4 | 13.7 | 470.8* | 21.0 | 13.7 |
| Troop surge at Kesari (+60%) | 1 | 12 | 20.4 | 13.7 | 470.8* | 21.0 | 13.7 |
| Troop surge at Kesari (+60%) | 2 | 12 | 20.4 | 15.7 | 470.8* | 21.0 | 13.7 |

`*` = the plan breaks a hard limit (vehicle capacity, bridge limit or depot stock) and is charged a penalty.
