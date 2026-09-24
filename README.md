# Chesterton

**CI proves your tests pass. Chesterton proves what they'd let through.**

A counterfactual code reviewer for AI-written pull requests. It deletes each
line of your patch in a parallel universe and reports which deletions your test
suite never noticed.

Status: implemented and benchmarked (v2, a registered null result), with a
live demo. See [`docs/superpowers/specs/`](docs/superpowers/specs/) for the
current design.

Licensed under the MIT License.

## Demo

Two of three recorded runs are live, plus one live call. The third, the
correct fix, is added once its review run is recorded. The URL is added
after the first deploy.

1. **Wrong patch, caught:** an agent patch that passed SWE-bench and UTBoost proved wrong. Chesterton names the untested behaviour and writes a regression test, verified by execution, that also holds on the correct fix.
2. **The honest limit:** a verified test that encodes the agent's own bug.
3. **The correct fix:** the reference patch, well defended. (coming)

## How this runs on Nebius

- **Sandboxes:** Nebius Token Factory Sandboxes (`https://api.tokenfactory.nebius.com/sandboxes/`). One seed checkpoint per pull request, forked once per mutant, 24 at a time.
- **Models** on Token Factory (`https://api.tokenfactory.nebius.com/v1/`): `nvidia/Nemotron-3_5-Lightning` proposes mutants, `nvidia/nemotron-3-super-120b-a12b` triages survivors, and `nvidia/Nemotron-3-Ultra-550b-a55b` writes the regression test. The model ids are defined in `src/chesterton/llm/client.py`.
- **The demo's live call:** `api/why.py` makes a real Nemotron Super call through `chesterton.demo.why.answer`. It is capped at 60 an hour and fails closed.
- **Deploy:** Vercel environment variables:
  - `NEBIUS_API_KEY` (server-side only);
  - `UPSTASH_REDIS_REST_URL` / `UPSTASH_REDIS_REST_TOKEN`, or the Upstash Vercel integration's `KV_REST_API_URL` / `KV_REST_API_TOKEN`;
  - if the counter is unreachable, the live call fails closed with a 503 rather than calling the model.
- **Run it yourself:** `chesterton seed`, `chesterton run`, `chesterton review` (needs `NEBIUS_API_KEY` and `NEBIUS_PROJECT_ID`).
- **The benchmark:** pre-registered and reported as registered, including its null result. See `docs/superpowers/specs/2026-09-18-chesterton-design.md` §17.
