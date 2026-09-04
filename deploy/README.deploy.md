# Self-hosted deploy (socialchoice2.karsooghmehregan.ir)

Upstream targets Vercel. This directory holds what is needed to run the app on a
plain Docker host behind nginx instead.

## Layout on the server

The files in this directory are placed one level *above* the clone:

    ~/socialchoice2/
      app/                 <- this repository (contains Dockerfile, .dockerignore)
      docker-compose.yml   <- deploy/docker-compose.yml
      shim/                <- deploy/shim/
      .env                 <- secrets, chmod 600, never committed
      data/                <- legacy file store, unused once Redis is configured
      redis-data/          <- Redis persistence

`.env` holds `ORCAROUTER_API_KEY`, `ADMIN_PASSWORD` and `REDIS_REST_TOKEN`.
Compose reads it both as `env_file` for the app and for `${REDIS_REST_TOKEN}`
interpolation.

## Why the app.py patch

`/api/evaluate`, `/api/examples` and `/api/state1/evaluate` are declared
`async def` but call into `workshop.py`, which talks to the LLM with blocking
`requests`. On an event loop that stalls every other request in the worker for
the whole duration of the LLM call. Wrapping those calls in
`starlette.concurrency.run_in_threadpool` keeps the loop free.

Measured on the deployed instance: a single `/api/evaluate` takes 5.79s; four
issued in parallel finish in 6.02s wall, and `/api/health` still answers in
0.22s while all four are in flight.

## Why the Redis shim

The app runs with `--workers 3`. In file-store mode `workshop.py` guards the
store with a `threading.Lock()`, which does not span worker processes, and every
write is a read-modify-write of the whole JSON document — so concurrent workers
lose writes, including the session table.

Setting `UPSTASH_REDIS_REST_URL` / `UPSTASH_REDIS_REST_TOKEN` switches
`workshop.py` onto its Redis path, where `_StoreLock` takes a real `SET NX EX`
lock. Upstash itself is not reachable from this host, so `shim/` implements the
subset of the Upstash REST protocol that `workshop.py` uses — `SET`, `GET` and
`DEL`, posted as a JSON array, answered as `{"result": ...}` — in front of a
local Redis container.

Verified after the switch: 24 parallel account creations all returned 200 and
all 24 accounts were present afterwards.

## Deploy

    rsync -az --delete --exclude .git <clone>/ <host>:~/socialchoice2/app/
    rsync -az deploy/ <host>:~/socialchoice2/
    ssh <host> 'cd ~/socialchoice2 && docker compose up -d --build'

nginx terminates on port 80 and proxies to `127.0.0.1:8027`; TLS and the
http->https redirect are handled by the CDN in front of the host.
