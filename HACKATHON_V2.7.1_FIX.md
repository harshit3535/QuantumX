# Astra / QuantumX v2.7.1 Fix Notes

## Fixed: coding requests routed as normal chat
A common typo such as `creat a login page frontend` previously missed the strict build-verb heuristic and could be routed to the general agent, producing a summary like `[html]` instead of the actual files. The build heuristic now accepts the common `creat` typo so these requests reach the code build/review team.

## Fixed: Enter in composer
The message textarea now treats **Enter** as Send and **Shift+Enter** as newline. `preventDefault()` prevents the textarea from moving to the next line when the user intends to submit.

## Cache busting
Frontend static assets are served with cache-busting version `271` so the browser is less likely to retain the previous JavaScript after deployment.

## Version
Astra / QuantumX `2.7.1`.
