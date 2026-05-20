> ## Documentation Index
> Fetch the complete documentation index at: https://docs.turso.tech/llms.txt
> Use this file to discover all available pages before exploring further.


Examples:https://github.com/tursodatabase/libsql-python/tree/main/examples


# Turso Quickstart (Python)

> Get started with Turso and Python in a few simple steps.

In this Python quickstart we will learn how to:

* Install the Turso package
* Connect to a local or remote database
* Execute a query using SQL
* Sync changes to local database

## Recommended: pyturso (Local / Embedded)

`pyturso` is the recommended package for local and embedded use cases. It is built on the Turso Database engine — a ground-up rewrite of SQLite with concurrent writes (MVCC) and async I/O. The API follows the standard Python `sqlite3` interface, so it works as a drop-in replacement.

<Steps>
  <Step title="Install">
    ```bash theme={null}
    uv add pyturso
    ```

    Or with pip:

    ```bash theme={null}
    pip install pyturso
    ```
  </Step>

  <Step title="Connect">
    ```py theme={null}
    import turso

    db = turso.connect("app.db")
    ```

    In-memory databases are also supported:

    ```py theme={null}
    db = turso.connect(":memory:")
    ```
  </Step>

  <Step title="Execute">
    ```py theme={null}
    db.execute("CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, name TEXT)")
    db.execute("INSERT INTO users (name) VALUES (?)", ("Alice",))
    db.commit()

    for row in db.execute("SELECT * FROM users"):
        print(row)
    ```
  </Step>

  <Step title="Sync (push and pull)">
    If you need to sync your local database with Turso Cloud, use `turso.sync`:

    ```py theme={null}
    import os
    import turso.sync

    db = turso.sync.connect(
        "app.db",
        remote_url=os.environ["TURSO_DATABASE_URL"],
        auth_token=os.environ["TURSO_AUTH_TOKEN"],
    )

    db.execute("INSERT INTO users (name) VALUES (?)", ("Bob",))
    db.commit()

    # Push local writes to Turso Cloud
    db.push()

    # Pull remote changes to local database
    db.pull()
    ```

    All reads and writes happen against the local database file — fast, offline-capable. `push()` sends your changes to the cloud. `pull()` brings remote changes down. See [Turso Sync](/sync/usage) for details on conflict resolution, checkpointing, and more.
  </Step>
</Steps>

## Remote Access (Over-the-Wire)

If your application needs to query a Turso Cloud database directly over the network (e.g., from a web server or serverless function), you can use the `libsql` package. It connects to your database via HTTP — no local file needed.

<Info>
  For most applications, we recommend running a local database with [Turso Sync](/sync/usage) (`turso.sync`) instead — it gives you faster reads, offline support, and lower latency. Remote access is useful when you cannot store a local database file (e.g., stateless serverless environments).
</Info>

<Steps>
  <Step title="Retrieve database credentials">
    You will need an existing database to continue. If you don't have one, [create one](/quickstart).

    <Snippet file="retrieve-database-credentials.mdx" />

    <Info>You will want to store these as environment variables.</Info>
  </Step>

  <Step title="Install">
    ```bash theme={null}
    uv add libsql
    ```

    Or with pip:

    ```bash theme={null}
    pip install libsql
    ```
  </Step>

  <Step title="Connect and query">
    ```py theme={null}
    import os
    import libsql

    conn = libsql.connect(
        database=os.environ["TURSO_DATABASE_URL"],
        auth_token=os.environ["TURSO_AUTH_TOKEN"],
    )

    conn.execute("CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, name TEXT)")
    conn.execute("INSERT INTO users (name) VALUES (?)", ("Alice",))
    conn.commit()

    rows = conn.execute("SELECT * FROM users").fetchall()
    print(rows)
    ```
  </Step>
</Steps>

## Embedded Replicas (libsql)

The `libsql` package also supports Embedded Replicas — local reads from a file, with writes sent to the cloud primary and reflected back to the replica. Embedded Replicas are fully supported in production. For new projects that need sync, we recommend `turso.sync` instead: both reads and writes are local, and you sync explicitly with `push()` / `pull()`.

See the [reference](/sdk/python/reference) for full documentation on Embedded Replicas, encryption, and periodic sync.
> ## Documentation Index
> Fetch the complete documentation index at: https://docs.turso.tech/llms.txt
> Use this file to discover all available pages before exploring further.

# Reference

> Python Reference for Turso

Turso offers two Python packages:

|                       | `pyturso`                       | `libsql`                                       |
| --------------------- | ------------------------------- | ---------------------------------------------- |
| **Use case**          | Local / embedded database, sync | Existing libSQL codebases                      |
| **Engine**            | Turso Database (rewrite)        | libSQL (SQLite fork)                           |
| **Concurrent writes** | Yes (MVCC)                      | Not supported                                  |
| **Sync**              | push/pull (local-first)         | Embedded Replicas (writes go to cloud primary) |
| **API**               | Python `sqlite3`-compatible     | Python `sqlite3`-compatible                    |

**Starting a new project?** Use `pyturso` — it is built on the Turso Database engine with concurrent writes and local-first sync.

## pyturso

For local and embedded use. Built on the Turso Database engine with concurrent writes (MVCC) and async I/O.

### Installing

```bash theme={null}
pip install pyturso
```

### Connecting

```py theme={null}
import turso

conn = turso.connect("app.db")
```

In-memory databases are also supported:

```py theme={null}
conn = turso.connect(":memory:")
```

### Querying

```py theme={null}
conn.execute("CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, name TEXT)")
conn.execute("INSERT INTO users (name) VALUES (?)", ("Alice",))
conn.commit()

for row in conn.execute("SELECT * FROM users"):
    print(row)
```

### Encryption

Encrypt local databases at rest using the `encryption` option:

```py theme={null}
from turso import connect, EncryptionOpts

conn = connect("encrypted.db",
               experimental_features="encryption",
               encryption=EncryptionOpts(cipher="aegis256",
                                         hexkey="b1bbfda4f589dc9daaf004fe21111e00dc00c98237102f5c7002a5669fc76327"))
```

Supported ciphers: `aegis256`, `aegis256x2`, `aegis128l`, `aegis128x2`, `aegis128x4`, `aes256gcm`, `aes128gcm`.

Encrypted databases cannot be read as standard SQLite databases — you must use the Turso Database engine to open them.

<Info>
  Turso Cloud databases can also be encrypted with bring-your-own-key — [learn more](/cloud/encryption).
</Info>

## libsql (libSQL)

The `libsql` package is built on [libSQL](https://github.com/tursodatabase/libsql), the open-source fork of SQLite that powers Turso Cloud today. It is production-ready and battle-tested, and is the right choice when you are working with an existing `libsql`-based codebase.

<Info>
  With `libsql` Embedded Replicas, reads are local and writes are sent to the cloud primary, then reflected back to the replica. Embedded Replicas are fully supported. For new projects that need sync, we recommend `turso.sync` — see the [quickstart](/sdk/python/quickstart).
</Info>

## Embedded Replicas

<Info>
  For workloads that need **offline writes**, **bidirectional sync**, or **multi-writer convergence**, we recommend `turso.sync` — both reads and writes are local, and you sync explicitly with `push()` / `pull()`. See the [quickstart](/sdk/python/quickstart).
</Info>

You can work with [embedded replicas](/features/embedded-replicas) that can sync from the remote database to a local SQLite file, and delegate writes to the remote primary database:

```py theme={null}
import os

import libsql

conn = libsql.connect("local.db", sync_url=os.getenv("LIBSQL_URL"),
                      auth_token=os.getenv("LIBSQL_AUTH_TOKEN"))
conn.execute("CREATE TABLE IF NOT EXISTS users (id INTEGER);")
conn.execute("INSERT INTO users(id) VALUES (1);")
conn.commit()

print(conn.execute("select * from users").fetchall())
```

<Snippet file="embedded-replicas-warning.mdx" />

### Periodic Sync

You can automatically sync at intervals by passing time in seconds to the `sync_interval` option. For example, to sync every minute, you can use the following code:

```py theme={null}
conn = libsql.connect("local.db", sync_interval=60, sync_url=os.getenv("LIBSQL_URL"),
                      auth_token=os.getenv("LIBSQL_AUTH_TOKEN"))
```

### Manual Sync

The `Sync` function allows you to sync manually the local database with the remote counterpart:

```py theme={null}
conn.execute("INSERT INTO users(id) VALUES (2);")
conn.commit()
conn.sync()
```

## Encryption

<Warning>
  For new projects, we recommend [`pyturso`](#pyturso) for local encryption — it is built on the Turso Database engine with better performance and concurrent write support.
</Warning>

To enable encryption on a SQLite file, pass the encryption secret to the `encryption_key` option:

```py theme={null}
conn = libsql.connect("encrypted.db", sync_url=os.getenv("LIBSQL_URL"),
                      auth_token=os.getenv("LIBSQL_AUTH_TOKEN"),
                      encryption_key=os.getenv("ENCRYPTION_KEY"))
```

<Info>
  Encrypted databases appear as raw data and cannot be read as standard SQLite databases. You must use the libSQL client for any operations — [learn more](/libsql#encryption-at-rest).
</Info>
> ## Documentation Index
> Fetch the complete documentation index at: https://docs.turso.tech/llms.txt
> Use this file to discover all available pages before exploring further.

# Usage

> How to enable and use sync with Turso across TypeScript, Python, and Go.

This guide shows how to set up a Turso database and use the sync features from your application.

<Note>
  This particular usage uses the Turso Cloud to sync the local Turso databases and assumes that you have an account.
</Note>

<Steps>
  <Step title="1. Setup Turso Cloud database">
    * Follow our [Quickstart](/quickstart) to install the CLI, create a database

    * Get the database URL (`libsql://...`):

    ```
    turso db show <db>
    ```

    * Create a token for your app:

    ```
    turso db tokens create <db>
    ```
  </Step>

  <Step title="2. Setup a basic connection with sync">
    You need three essentials to enable sync:

    * Local path: where the local, synced tursodb file is stored
    * Remote URL: your Turso Cloud URL (`libsql://...`)
    * Auth token: Turso Cloud token to authenticate requests

    <CodeGroup>
      ```ts TypeScript theme={null}
      import { connect } from '@tursodatabase/sync';

      const db = await connect({
        path: './app.db',                               // local path
        url: 'libsql://...',                            // remote URL (generated with turso db show <db-name> --url)
        authToken: process.env.TURSO_AUTH_TOKEN,        // authentication token (generated with turso db tokens create <db-name>)
        // longPollTimeoutMs: 10_000,                   // optional: server waits before replying to pull
        // bootstrapIfEmpty: false,                     // set to false to avoid bootstrapping on first run
      });
      ```

      ```py Python theme={null}
      import os
      import turso.sync

      conn = turso.sync.connect(
          path="./app.db",                                  # local path
          remote_url="libsql://...",                        # remote URL (generated with turso db show <db-name> --url)
          remote_auth_token=os.environ["TURSO_AUTH_TOKEN"], # authentication token (generated with turso db tokens create <db-name>)
          # long_poll_timeout_ms=10_000,                    # optional: server waits before replying to pull
          # bootstrap_if_empty=False,                       # set to false to avoid bootstrapping on first run
      )
      ```

      ```go Go theme={null}
      package main

      import (
      	"turso"
      )

      db, err := turso.NewTursoSyncDb(ctx, turso.TursoSyncDbConfig{
        Path:              "./app.db",                    // local path
        RemoteUrl:         "libsql://...",                // remote URL (generated with turso db show <db-name> --url)
        RemoteAuthToken:   os.Getenv("TURSO_AUTH_TOKEN"), // authentication token (generated with turso db tokens create <db-name>)
        // LongPollTimeoutMs: 10_000,                     // optional: server waits before replying to pull
        // BootstrapIfEmpty: false,                       // set to false to avoid bootstrapping on first run
      })
      ```
    </CodeGroup>

    <Note>
      On the first run, the local database is automatically bootstrapped from the remote — so the remote must be reachable during the initial connect.

      If you set `bootstrap_if_empty` to `false`, the local database will start empty instead.
      You can bootstrap or update it later at any time by explicitly calling `pull()`.
    </Note>
  </Step>

  <Step title="3. Push changes">
    Push sends your local changes to the Turso Cloud server. Under the hood, logical statements are sent, and on conflicts the strategy is "last push wins".

    <CodeGroup>
      ```ts TypeScript theme={null}
      await db.exec("CREATE TABLE IF NOT EXISTS notes(id TEXT PRIMARY KEY, body TEXT)");
      await db.exec("INSERT INTO notes VALUES ('n1', 'hello')");

      await db.push();
      ```

      ```py Python theme={null}
      conn.execute("CREATE TABLE IF NOT EXISTS notes(id TEXT PRIMARY KEY, body TEXT)")
      conn.commit()
      conn.execute("INSERT INTO notes VALUES ('n1', 'hello')")
      conn.commit()

      conn.push()
      ```

      ```go Go theme={null}
      // create *sql.DB instance
      conn, err := db.Connect(ctx)
      if err != nil {
        return err
      }

      _, err = conn.ExecContext(ctx, "CREATE TABLE IF NOT EXISTS notes(id TEXT PRIMARY KEY, body TEXT)")
      if err != nil {
        return err
      }
      _, err = conn.ExecContext(ctx, "INSERT INTO notes VALUES ('n1', 'hello')")
      if err != nil {
        return err
      }

      if err := db.Push(ctx); err != nil {
      	return err
      }
      ```
    </CodeGroup>
  </Step>

  <Step title="4. Pull changes">
    Pull fetches remote changes and applies them locally. It returns a boolean indicating whether anything changed.

    * Configure `long_poll_timeout_ms`/`LongPollTimeoutMs` if you want the server to wait for changes and avoid empty replies.
    * If you pushed earlier, a subsequent pull can still return that something changed due to server-side conflict resolution frames.

    <CodeGroup>
      ```ts TypeScript theme={null}
      // Returns true if anything changed locally
      const changed = await db.pull();
      console.info('pulled changes:', changed);
      ```

      ```py Python theme={null}
      changed = conn.pull()
      print("pulled changes:", changed)
      ```

      ```go Go theme={null}
      changed, err := db.Pull(ctx)
      if err != nil {
      	return err
      }
      log.Println("pulled changes:", changed)
      ```
    </CodeGroup>
  </Step>

  <Step title="5. Checkpoint">
    Checkpoint compacts the local WAL to bound local disk usage while preserving sync state.

    <CodeGroup>
      ```ts TypeScript theme={null}
      await db.checkpoint();
      ```

      ```py Python theme={null}
      conn.checkpoint()
      ```

      ```go Go theme={null}
      if err := db.Checkpoint(ctx); err != nil {
      	return err
      }
      ```
    </CodeGroup>
  </Step>

  <Step title="6. Stats">
    Stats help you observe sync behavior and usage (WAL sizes, last push/pull times, network usage, revision, etc.).

    <CodeGroup>
      ```ts TypeScript theme={null}
      const s = await db.stats();
      console.info({
        cdcOperations: s.cdcOperations,
        mainWalSize: s.mainWalSize,
        revertWalSize: s.revertWalSize,
        networkReceivedBytes: s.networkReceivedBytes,
        networkSentBytes: s.networkSentBytes,
        lastPullUnixTime: s.lastPullUnixTime,
        lastPushUnixTime: s.lastPushUnixTime,
        revision: s.revision,
      });
      ```

      ```py Python theme={null}
      s = conn.stats()
      print({
          "cdc_operations": s.cdc_operations,
          "main_wal_size": s.main_wal_size,
          "revert_wal_size": s.revert_wal_size,
          "network_received_bytes": s.network_received_bytes,
          "network_sent_bytes": s.network_sent_bytes,
          "last_pull_unix_time": s.last_pull_unix_time,
          "last_push_unix_time": s.last_push_unix_time,
          "revision": s.revision,
      })
      ```

      ```go Go theme={null}
      s, err := db.Stats(ctx)
      if err != nil {
      	return err
      }
      log.Printf("stats: cdc=%v, main=%d revert=%d rx=%d tx=%d pull=%d push=%d revision=%s",
        s.CdcOperations,
        s.MainWalSize,
        s.RevertWalSize,
        s.NetworkReceivedBytes,
        s.NetworkSentBytes,
        s.LastPullUnixTime,
        s.LastPushUnixTime,
        s.Revision,
      )
      ```
    </CodeGroup>
  </Step>
</Steps>

## Offline-first writes

If your app needs to accept writes without internet connectivity, write locally and call `push()` when the connection is available. All changes are safely stored in the local database file until they can be synced.

<CodeGroup>
  ```ts TypeScript theme={null}
  import { connect } from '@tursodatabase/sync';

  // bootstrapIfEmpty: false lets the app start offline without
  // needing to reach the remote on first launch
  const db = await connect({
    path: './local.db',
    url: process.env.TURSO_URL!,
    authToken: process.env.TURSO_AUTH_TOKEN!,
    bootstrapIfEmpty: false,
  });

  async function syncWhenOnline(db) {
    try {
      await db.push();
    } catch (e) {
      // No connectivity — changes are safe in the local file
      // and will sync on the next push() call
    }
  }

  // On app launch, pull the latest state if online
  try {
    await db.pull();
  } catch (e) {
    // Offline — local data is still available for reads and writes
  }

  // On a timer or connectivity event
  await syncWhenOnline(db);
  ```

  ```py Python theme={null}
  import os
  import turso.sync

  # bootstrap_if_empty=False lets the app start offline without
  # needing to reach the remote on first launch
  conn = turso.sync.connect(
      path="./local.db",
      remote_url=os.environ["TURSO_URL"],
      remote_auth_token=os.environ["TURSO_AUTH_TOKEN"],
      bootstrap_if_empty=False,
  )

  def sync_when_online(conn):
      try:
          conn.push()
      except Exception:
          # No connectivity — changes are safe in the local file
          # and will sync on the next push() call
          pass

  # On app launch, pull the latest state if online
  try:
      conn.pull()
  except Exception:
      # Offline — local data is still available for reads and writes
      pass

  # On a timer or connectivity event
  sync_when_online(conn)
  ```

  ```go Go theme={null}
  // BootstrapIfEmpty: false lets the app start offline without
  // needing to reach the remote on first launch
  db, err := turso.NewTursoSyncDb(ctx, turso.TursoSyncDbConfig{
  	Path:             "./local.db",
  	RemoteUrl:        os.Getenv("TURSO_URL"),
  	RemoteAuthToken:  os.Getenv("TURSO_AUTH_TOKEN"),
  	BootstrapIfEmpty: false,
  })

  func syncWhenOnline(ctx context.Context, db *turso.TursoSyncDb) {
  	if err := db.Push(ctx); err != nil {
  		// No connectivity — changes are safe in the local file
  		// and will sync on the next Push() call
  		log.Println("push deferred:", err)
  	}
  }

  // On app launch, pull the latest state if online
  if _, err := db.Pull(ctx); err != nil {
  	// Offline — local data is still available for reads and writes
  	log.Println("pull deferred:", err)
  }

  // On a timer or connectivity event
  syncWhenOnline(ctx, db)
  ```
</CodeGroup>

This is the modern equivalent of the `offline: true` flag from [`@libsql/client` Embedded Replicas](/features/embedded-replicas/introduction). With Turso Sync, all reads and writes happen locally by default — you control when to sync with explicit `push()` and `pull()` calls.
> ## Documentation Index
> Fetch the complete documentation index at: https://docs.turso.tech/llms.txt
> Use this file to discover all available pages before exploring further.

# Local Sync Server

> Use the Turso CLI as a local sync server for development and testing without Turso Cloud.

The `tursodb` CLI includes a built-in sync server that you can run locally. This lets you develop and test sync workflows entirely on your machine — no Turso Cloud account required.

<Info>
  The local sync server implements the same sync protocol as Turso Cloud, so your application code works the same way in both environments.
</Info>

## Starting the server

Pass `--sync-server` with an address to start the sync server. The database argument specifies where the server stores its data:

```bash theme={null}
tursodb ./server.db --sync-server 0.0.0.0:8080
```

This starts a sync server listening on port `8080`, backed by `./server.db`.

## Connecting clients

Point your sync client at `http://localhost:8080`. No auth token is needed for the local server.

<CodeGroup>
  ```ts TypeScript theme={null}
  import { connect } from '@tursodatabase/sync';

  const db = await connect({
    path: './local-replica.db',
    url: 'http://localhost:8080',
  });
  ```

  ```py Python theme={null}
  import turso.sync

  conn = turso.sync.connect(
      path="./local-replica.db",
      remote_url="http://localhost:8080",
  )
  ```

  ```go Go theme={null}
  package main

  import (
  	"turso"
  )

  db, err := turso.NewTursoSyncDb(ctx, turso.TursoSyncDbConfig{
      Path:      "./local-replica.db",
      RemoteUrl: "http://localhost:8080",
  })
  ```
</CodeGroup>

Once connected, all sync operations (`push`, `pull`, `checkpoint`, `stats`) work exactly as described in the [Usage](/sync/usage) guide.

## Example: full local sync workflow

This example walks through a complete workflow — starting the server, writing data from one client, and syncing it to another.

<Steps>
  <Step title="1. Start the sync server">
    Open a terminal and start the server:

    ```bash theme={null}
    tursodb ./server.db --sync-server 0.0.0.0:8080
    ```
  </Step>

  <Step title="2. Write and push from Client A">
    <CodeGroup>
      ```ts TypeScript theme={null}
      import { connect } from '@tursodatabase/sync';

      const clientA = await connect({
        path: './client-a.db',
        url: 'http://localhost:8080',
      });

      await clientA.exec("CREATE TABLE IF NOT EXISTS notes (id TEXT PRIMARY KEY, body TEXT)");
      await clientA.exec("INSERT INTO notes VALUES ('n1', 'hello from client A')");

      await clientA.push();
      ```

      ```py Python theme={null}
      import turso.sync

      client_a = turso.sync.connect(
          path="./client-a.db",
          remote_url="http://localhost:8080",
      )

      client_a.execute("CREATE TABLE IF NOT EXISTS notes (id TEXT PRIMARY KEY, body TEXT)")
      client_a.commit()
      client_a.execute("INSERT INTO notes VALUES ('n1', 'hello from client A')")
      client_a.commit()

      client_a.push()
      ```

      ```go Go theme={null}
      clientA, err := turso.NewTursoSyncDb(ctx, turso.TursoSyncDbConfig{
          Path:      "./client-a.db",
          RemoteUrl: "http://localhost:8080",
      })
      if err != nil {
          return err
      }
      connA, _ := clientA.Connect(ctx)

      connA.ExecContext(ctx, "CREATE TABLE IF NOT EXISTS notes (id TEXT PRIMARY KEY, body TEXT)")
      connA.ExecContext(ctx, "INSERT INTO notes VALUES ('n1', 'hello from client A')")

      clientA.Push(ctx)
      ```
    </CodeGroup>
  </Step>

  <Step title="3. Pull from Client B">
    <CodeGroup>
      ```ts TypeScript theme={null}
      import { connect } from '@tursodatabase/sync';

      const clientB = await connect({
        path: './client-b.db',
        url: 'http://localhost:8080',
      });

      const changed = await clientB.pull();
      console.log('changes pulled:', changed);

      const rows = await clientB.query("SELECT * FROM notes");
      console.log(rows);
      // [{ id: 'n1', body: 'hello from client A' }]
      ```

      ```py Python theme={null}
      import turso.sync

      client_b = turso.sync.connect(
          path="./client-b.db",
          remote_url="http://localhost:8080",
      )

      changed = client_b.pull()
      print("changes pulled:", changed)

      rows = client_b.execute("SELECT * FROM notes").fetchall()
      print(rows)
      # [('n1', 'hello from client A')]
      ```

      ```go Go theme={null}
      clientB, err := turso.NewTursoSyncDb(ctx, turso.TursoSyncDbConfig{
          Path:      "./client-b.db",
          RemoteUrl: "http://localhost:8080",
      })
      if err != nil {
          return err
      }

      changed, _ := clientB.Pull(ctx)
      log.Println("changes pulled:", changed)

      connB, _ := clientB.Connect(ctx)
      rows, _ := connB.QueryContext(ctx, "SELECT * FROM notes")
      ```
    </CodeGroup>
  </Step>
</Steps>
> ## Documentation Index
> Fetch the complete documentation index at: https://docs.turso.tech/llms.txt
> Use this file to discover all available pages before exploring further.

# Partial sync

> Sync only what you need. Faster cold starts and lower bandwidth by lazily fetching database pages on demand.

<Note>
  This particular usage uses the Turso Cloud to sync the local Turso databases and assumes that you have an account.
</Note>

Partial sync lets your app open and use a database without downloading the entire file.
The client lazily fetches pages of the database file from the Turso Cloud when a query touches data that is not present locally.
This reduces startup time and network usage for large databases, while remaining fully compatible with the push/pull methods used
by Turso's standard `sync` solution.

<Note>
  * Reads on not-yet-downloaded data transparently trigger on-demand page fetches.
  * Writes still apply locally first and are pushed as logical statements.
</Note>

## Modes

Two bootstrap strategies define what is present locally at connect time:

* **Prefix bootstrap**: download the first N bytes of the database file.
  * Good default when you want a minimal, predictable starting footprint.
* **Query bootstrap**: download pages touched by running a server-side SQL query.
  * Ideal to hydrate only a narrow working set (e.g., a single user's rows, small tables with metadata, references, etc).

Both modes continue to lazily fetch missing pages on demand.

### Prefix bootstrap

<CodeGroup>
  ```ts TypeScript theme={null}
  import { connect } from '@tursodatabase/sync';

  const db = await connect({
    path: './app.db',
    url: 'libsql://...',
    authToken: process.env.TURSO_AUTH_TOKEN,
    partialSyncExperimental: {
      bootstrapStrategy: { kind: 'prefix', length: 128 * 1024 }, // 128 KiB
    },
  });
  ```

  ```py Python theme={null}
  import os
  import turso.sync

  conn = turso.sync.connect(
      path="./app.db",
      remote_url="libsql://...",
      remote_auth_token=os.environ["TURSO_AUTH_TOKEN"],
      partial_sync_opts=turso.sync.PartialSyncOpts(
          bootstrap_strategy=turso.sync.PartialSyncPrefixBootstrap(length=128 * 1024),
      ),
  )
  ```

  ```go Go theme={null}
  import (
  	"turso"
  )

  db, err := turso.NewTursoSyncDb(context.Background(), turso.TursoSyncDbConfig{
    Path:            "./app.db",
    RemoteUrl:       "libsql://...",
    RemoteAuthToken: os.Getenv("TURSO_AUTH_TOKEN"),
    PartialSyncConfig: turso.TursoPartialSyncConfig{
      BoostrapStrategyPrefix: 128 * 1024, // 128 KiB
    },
  })
  ```
</CodeGroup>

### Query bootstrap

<CodeGroup>
  ```ts TypeScript theme={null}
  import { connect } from '@tursodatabase/sync';

  const db = await connect({
    path: './app.db',
    url: 'libsql://...',
    authToken: process.env.TURSO_AUTH_TOKEN,
    partialSyncExperimental: {
      bootstrapStrategy: {
        kind: 'query',
        query: `SELECT * FROM messages WHERE user_id = 'u_123' LIMIT 100`,
      },
    },
  });
  ```

  ```py Python theme={null}
  import turso.sync

  conn = turso.sync.connect(
      path=":memory:",
      remote_url="libsql://...",
      partial_sync_opts=turso.sync.PartialSyncOpts(
          bootstrap_strategy=turso.sync.PartialSyncQueryBootstrap(
              query="SELECT * FROM messages WHERE user_id = 'u_123' LIMIT 100"
          ),
      ),
  )
  ```

  ```go Go theme={null}
  import (
  	"turso"
  )

  db, err := turso.NewTursoSyncDb(context.Background(), turso.TursoSyncDbConfig{
    Path:            "./app.db",
    RemoteUrl:       "libsql://...",
    RemoteAuthToken: os.Getenv("TURSO_AUTH_TOKEN"),
    PartialSyncConfig: turso.TursoPartialSyncConfig{
      BoostrapStrategyQuery: "SELECT * FROM messages WHERE user_id = 'u_123' LIMIT 100",
    },
  })
  ```
</CodeGroup>

## Optimizations

### Segment size (batched lazy reads)

<Frame>
  <div id="seg-viz" style={{ padding: '1rem 0.5rem' }}>
    <style>
      {`
              #s1-cell-1, #s1-cell-2, #s1-cell-3, #s1-cell-4, #s1-cell-5, #s1-cell-6, #s1-cell-7, #s1-cell-8, #s1-cell-9, #s1-cell-10, #s1-cell-11, #s1-cell-12 { cursor: pointer; }
              #s1-cell-1:hover rect, #s1-cell-2:hover rect, #s1-cell-3:hover rect, #s1-cell-4:hover rect, #s1-cell-5:hover rect, #s1-cell-6:hover rect, #s1-cell-7:hover rect, #s1-cell-8:hover rect, #s1-cell-9:hover rect, #s1-cell-10:hover rect, #s1-cell-11:hover rect, #s1-cell-12:hover rect { filter: brightness(1.2); }
            `}
    </style>

    <svg viewBox="0 0 540 140" xmlns="http://www.w3.org/2000/svg" style={{ width: '100%', minWidth: '480px', maxWidth: '620px', display: 'block', margin: '0 auto' }}>
      <defs>
        <marker id="arrow" markerWidth="8" markerHeight="6" refX="8" refY="3" orient="auto">
          <polygon points="0 0, 8 3, 0 6" fill="#6b7280" />
        </marker>
      </defs>

      <g id="seg-state-1">
        <text x="76" y="14" fill="#9ca3af" fontFamily="ui-monospace,monospace" fontSize="10" textAnchor="middle">select page</text>

        {/* Row 1 */}

        <g id="s1-cell-1"><rect id="s1-rect-1" x="10" y="22" width="30" height="30" fill="#1ebca1" stroke="#1ebca1" strokeWidth="2" rx="4" /><text id="s1-text-1" x="25" y="42" fill="#0a0a0a" fontFamily="ui-monospace,monospace" fontSize="12" textAnchor="middle" fontWeight="bold" style={{ pointerEvents:'none' }}>1</text></g>
        <g id="s1-cell-2"><rect id="s1-rect-2" x="44" y="22" width="30" height="30" fill="#1ebca1" stroke="#1ebca1" strokeWidth="2" rx="4" /><text id="s1-text-2" x="59" y="42" fill="#0a0a0a" fontFamily="ui-monospace,monospace" fontSize="12" textAnchor="middle" fontWeight="bold" style={{ pointerEvents:'none' }}>2</text></g>
        <g id="s1-cell-3"><rect id="s1-rect-3" x="78" y="22" width="30" height="30" fill="#1ebca1" stroke="#1ebca1" strokeWidth="2" rx="4" /><text id="s1-text-3" x="93" y="42" fill="#0a0a0a" fontFamily="ui-monospace,monospace" fontSize="12" textAnchor="middle" fontWeight="bold" style={{ pointerEvents:'none' }}>3</text></g>
        <g id="s1-cell-4"><rect id="s1-rect-4" x="112" y="22" width="30" height="30" fill="#2a2a4a" stroke="#3a3a5a" strokeWidth="1" rx="4" /><text id="s1-text-4" x="127" y="42" fill="#6b7280" fontFamily="ui-monospace,monospace" fontSize="12" textAnchor="middle" style={{ pointerEvents:'none' }}>4</text></g>

        {/* Row 2 */}

        <g id="s1-cell-5"><rect id="s1-rect-5" x="10" y="56" width="30" height="30" fill="#2a2a4a" stroke="#3a3a5a" strokeWidth="1" rx="4" /><text id="s1-text-5" x="25" y="76" fill="#6b7280" fontFamily="ui-monospace,monospace" fontSize="12" textAnchor="middle" style={{ pointerEvents:'none' }}>5</text></g>
        <g id="s1-cell-6"><rect id="s1-rect-6" x="44" y="56" width="30" height="30" fill="#1ebca1" stroke="#1ebca1" strokeWidth="2" rx="4" /><text id="s1-text-6" x="59" y="76" fill="#0a0a0a" fontFamily="ui-monospace,monospace" fontSize="12" textAnchor="middle" fontWeight="bold" style={{ pointerEvents:'none' }}>6</text></g>
        <g id="s1-cell-7"><rect id="s1-rect-7" x="78" y="56" width="30" height="30" fill="#2a2a4a" stroke="#3a3a5a" strokeWidth="1" rx="4" /><text id="s1-text-7" x="93" y="76" fill="#6b7280" fontFamily="ui-monospace,monospace" fontSize="12" textAnchor="middle" style={{ pointerEvents:'none' }}>7</text></g>
        <g id="s1-cell-8"><rect id="s1-rect-8" x="112" y="56" width="30" height="30" fill="#2a2a4a" stroke="#3a3a5a" strokeWidth="1" rx="4" /><text id="s1-text-8" x="127" y="76" fill="#6b7280" fontFamily="ui-monospace,monospace" fontSize="12" textAnchor="middle" style={{ pointerEvents:'none' }}>8</text></g>

        {/* Row 3 */}

        <g id="s1-cell-9"><rect id="s1-rect-9" x="10" y="90" width="30" height="30" fill="#2a2a4a" stroke="#3a3a5a" strokeWidth="1" rx="4" /><text id="s1-text-9" x="25" y="110" fill="#6b7280" fontFamily="ui-monospace,monospace" fontSize="12" textAnchor="middle" style={{ pointerEvents:'none' }}>9</text></g>
        <g id="s1-cell-10"><rect id="s1-rect-10" x="44" y="90" width="30" height="30" fill="#2a2a4a" stroke="#3a3a5a" strokeWidth="1" rx="4" /><text id="s1-text-10" x="59" y="110" fill="#6b7280" fontFamily="ui-monospace,monospace" fontSize="12" textAnchor="middle" style={{ pointerEvents:'none' }}>10</text></g>
        <g id="s1-cell-11"><rect id="s1-rect-11" x="78" y="90" width="30" height="30" fill="#2a2a4a" stroke="#3a3a5a" strokeWidth="1" rx="4" /><text id="s1-text-11" x="93" y="110" fill="#6b7280" fontFamily="ui-monospace,monospace" fontSize="12" textAnchor="middle" style={{ pointerEvents:'none' }}>11</text></g>
        <g id="s1-cell-12"><rect id="s1-rect-12" x="112" y="90" width="30" height="30" fill="#2a2a4a" stroke="#3a3a5a" strokeWidth="1" rx="4" /><text id="s1-text-12" x="127" y="110" fill="#6b7280" fontFamily="ui-monospace,monospace" fontSize="12" textAnchor="middle" style={{ pointerEvents:'none' }}>12</text></g>
      </g>

      <g id="seg-arrow-1" style={{ transition: 'opacity 0.3s' }}>
        <line x1="152" y1="71" x2="188" y2="71" stroke="#6b7280" strokeWidth="2" markerEnd="url(#arrow)" />

        <text id="seg-arrow-label" x="170" y="64" fill="#f97316" fontFamily="ui-monospace,monospace" fontSize="9" textAnchor="middle">read(7)</text>
      </g>

      <g id="seg-state-2" style={{ transition: 'opacity 0.3s' }}>
        <text x="268" y="14" fill="#f97316" fontFamily="ui-monospace,monospace" fontSize="10" textAnchor="middle">fetching segment</text>

        {/* Brackets */}

        <rect id="s2-bracket-1" x="195" y="22" width="4" height="30" rx="2" fill="#f97316" style={{ opacity: 0, transition: 'opacity 0.3s' }} />

        <rect id="s2-bracket-2" x="195" y="56" width="4" height="30" rx="2" fill="#f97316" style={{ opacity: 1, transition: 'opacity 0.3s' }} />

        <rect id="s2-bracket-3" x="195" y="90" width="4" height="30" rx="2" fill="#f97316" style={{ opacity: 0, transition: 'opacity 0.3s' }} />

        {/* Row 1 */}

        <g><rect id="s2-rect-1" x="203" y="22" width="30" height="30" fill="#1ebca1" stroke="#1ebca1" strokeWidth="2" rx="4" /><text id="s2-text-1" x="218" y="42" fill="#0a0a0a" fontFamily="ui-monospace,monospace" fontSize="12" textAnchor="middle" fontWeight="bold">1</text></g>
        <g><rect id="s2-rect-2" x="237" y="22" width="30" height="30" fill="#1ebca1" stroke="#1ebca1" strokeWidth="2" rx="4" /><text id="s2-text-2" x="252" y="42" fill="#0a0a0a" fontFamily="ui-monospace,monospace" fontSize="12" textAnchor="middle" fontWeight="bold">2</text></g>
        <g><rect id="s2-rect-3" x="271" y="22" width="30" height="30" fill="#1ebca1" stroke="#1ebca1" strokeWidth="2" rx="4" /><text id="s2-text-3" x="286" y="42" fill="#0a0a0a" fontFamily="ui-monospace,monospace" fontSize="12" textAnchor="middle" fontWeight="bold">3</text></g>
        <g><rect id="s2-rect-4" x="305" y="22" width="30" height="30" fill="#2a2a4a" stroke="#3a3a5a" strokeWidth="1" rx="4" /><text id="s2-text-4" x="320" y="42" fill="#6b7280" fontFamily="ui-monospace,monospace" fontSize="12" textAnchor="middle">4</text></g>

        {/* Row 2 */}

        <g><rect id="s2-rect-5" x="203" y="56" width="30" height="30" fill="#f97316" stroke="#f97316" strokeWidth="2" rx="4" /><text id="s2-text-5" x="218" y="76" fill="#0a0a0a" fontFamily="ui-monospace,monospace" fontSize="12" textAnchor="middle" fontWeight="bold">5</text></g>
        <g><rect id="s2-rect-6" x="237" y="56" width="30" height="30" fill="#1ebca1" stroke="#1ebca1" strokeWidth="2" rx="4" /><text id="s2-text-6" x="252" y="76" fill="#0a0a0a" fontFamily="ui-monospace,monospace" fontSize="12" textAnchor="middle" fontWeight="bold">6</text></g>
        <g><rect id="s2-rect-7" x="271" y="56" width="30" height="30" fill="#f97316" stroke="#fbbf24" strokeWidth="3" rx="4" /><text id="s2-text-7" x="286" y="76" fill="#0a0a0a" fontFamily="ui-monospace,monospace" fontSize="12" textAnchor="middle" fontWeight="bold">7</text></g>
        <g><rect id="s2-rect-8" x="305" y="56" width="30" height="30" fill="#f97316" stroke="#f97316" strokeWidth="2" rx="4" /><text id="s2-text-8" x="320" y="76" fill="#0a0a0a" fontFamily="ui-monospace,monospace" fontSize="12" textAnchor="middle" fontWeight="bold">8</text></g>

        {/* Row 3 */}

        <g><rect id="s2-rect-9" x="203" y="90" width="30" height="30" fill="#2a2a4a" stroke="#3a3a5a" strokeWidth="1" rx="4" /><text id="s2-text-9" x="218" y="110" fill="#6b7280" fontFamily="ui-monospace,monospace" fontSize="12" textAnchor="middle">9</text></g>
        <g><rect id="s2-rect-10" x="237" y="90" width="30" height="30" fill="#2a2a4a" stroke="#3a3a5a" strokeWidth="1" rx="4" /><text id="s2-text-10" x="252" y="110" fill="#6b7280" fontFamily="ui-monospace,monospace" fontSize="12" textAnchor="middle">10</text></g>
        <g><rect id="s2-rect-11" x="271" y="90" width="30" height="30" fill="#2a2a4a" stroke="#3a3a5a" strokeWidth="1" rx="4" /><text id="s2-text-11" x="286" y="110" fill="#6b7280" fontFamily="ui-monospace,monospace" fontSize="12" textAnchor="middle">11</text></g>
        <g><rect id="s2-rect-12" x="305" y="90" width="30" height="30" fill="#2a2a4a" stroke="#3a3a5a" strokeWidth="1" rx="4" /><text id="s2-text-12" x="320" y="110" fill="#6b7280" fontFamily="ui-monospace,monospace" fontSize="12" textAnchor="middle">12</text></g>
        <text id="seg-segment-label" x="268" y="132" fill="#f97316" fontFamily="ui-monospace,monospace" fontSize="9" textAnchor="middle">segment 5-8</text>
      </g>

      <g id="seg-arrow-2" style={{ transition: 'opacity 0.3s' }}>
        <line x1="345" y1="71" x2="381" y2="71" stroke="#6b7280" strokeWidth="2" markerEnd="url(#arrow)" />
      </g>

      <g id="seg-state-3" style={{ transition: 'opacity 0.3s' }}>
        <text x="461" y="14" fill="#1ebca1" fontFamily="ui-monospace,monospace" fontSize="10" textAnchor="middle">segment cached</text>

        {/* Row 1 */}

        <g><rect id="s3-rect-1" x="396" y="22" width="30" height="30" fill="#1ebca1" stroke="#1ebca1" strokeWidth="2" rx="4" /><text id="s3-text-1" x="411" y="42" fill="#0a0a0a" fontFamily="ui-monospace,monospace" fontSize="12" textAnchor="middle" fontWeight="bold">1</text></g>
        <g><rect id="s3-rect-2" x="430" y="22" width="30" height="30" fill="#1ebca1" stroke="#1ebca1" strokeWidth="2" rx="4" /><text id="s3-text-2" x="445" y="42" fill="#0a0a0a" fontFamily="ui-monospace,monospace" fontSize="12" textAnchor="middle" fontWeight="bold">2</text></g>
        <g><rect id="s3-rect-3" x="464" y="22" width="30" height="30" fill="#1ebca1" stroke="#1ebca1" strokeWidth="2" rx="4" /><text id="s3-text-3" x="479" y="42" fill="#0a0a0a" fontFamily="ui-monospace,monospace" fontSize="12" textAnchor="middle" fontWeight="bold">3</text></g>
        <g><rect id="s3-rect-4" x="498" y="22" width="30" height="30" fill="#2a2a4a" stroke="#3a3a5a" strokeWidth="1" rx="4" /><text id="s3-text-4" x="513" y="42" fill="#6b7280" fontFamily="ui-monospace,monospace" fontSize="12" textAnchor="middle">4</text></g>

        {/* Row 2 */}

        <g><rect id="s3-rect-5" x="396" y="56" width="30" height="30" fill="#1ebca1" stroke="#1ebca1" strokeWidth="2" rx="4" /><text id="s3-text-5" x="411" y="76" fill="#0a0a0a" fontFamily="ui-monospace,monospace" fontSize="12" textAnchor="middle" fontWeight="bold">5</text></g>
        <g><rect id="s3-rect-6" x="430" y="56" width="30" height="30" fill="#1ebca1" stroke="#1ebca1" strokeWidth="2" rx="4" /><text id="s3-text-6" x="445" y="76" fill="#0a0a0a" fontFamily="ui-monospace,monospace" fontSize="12" textAnchor="middle" fontWeight="bold">6</text></g>
        <g><rect id="s3-rect-7" x="464" y="56" width="30" height="30" fill="#1ebca1" stroke="#1ebca1" strokeWidth="2" rx="4" /><text id="s3-text-7" x="479" y="76" fill="#0a0a0a" fontFamily="ui-monospace,monospace" fontSize="12" textAnchor="middle" fontWeight="bold">7</text></g>
        <g><rect id="s3-rect-8" x="498" y="56" width="30" height="30" fill="#1ebca1" stroke="#1ebca1" strokeWidth="2" rx="4" /><text id="s3-text-8" x="513" y="76" fill="#0a0a0a" fontFamily="ui-monospace,monospace" fontSize="12" textAnchor="middle" fontWeight="bold">8</text></g>

        {/* Row 3 */}

        <g><rect id="s3-rect-9" x="396" y="90" width="30" height="30" fill="#2a2a4a" stroke="#3a3a5a" strokeWidth="1" rx="4" /><text id="s3-text-9" x="411" y="110" fill="#6b7280" fontFamily="ui-monospace,monospace" fontSize="12" textAnchor="middle">9</text></g>
        <g><rect id="s3-rect-10" x="430" y="90" width="30" height="30" fill="#2a2a4a" stroke="#3a3a5a" strokeWidth="1" rx="4" /><text id="s3-text-10" x="445" y="110" fill="#6b7280" fontFamily="ui-monospace,monospace" fontSize="12" textAnchor="middle">10</text></g>
        <g><rect id="s3-rect-11" x="464" y="90" width="30" height="30" fill="#2a2a4a" stroke="#3a3a5a" strokeWidth="1" rx="4" /><text id="s3-text-11" x="479" y="110" fill="#6b7280" fontFamily="ui-monospace,monospace" fontSize="12" textAnchor="middle">11</text></g>
        <g><rect id="s3-rect-12" x="498" y="90" width="30" height="30" fill="#2a2a4a" stroke="#3a3a5a" strokeWidth="1" rx="4" /><text id="s3-text-12" x="513" y="110" fill="#6b7280" fontFamily="ui-monospace,monospace" fontSize="12" textAnchor="middle">12</text></g>
      </g>
    </svg>

    <p id="seg-status" style={{ textAlign: 'center', color: '#f97316', fontSize: '0.8rem', margin: '0.5rem 0 0', fontFamily: 'ui-monospace, monospace', transition: 'color 0.3s' }}>
      Read page 7 → fetch segment 5-8 (3 new pages)
    </p>
  </div>
</Frame>

When the client needs a page that isn’t present locally, partial sync performs an on-demand fetch from the remote database.

To reduce round-trips and speed up these fetches, you can configure the **segment size**: instead of requesting a single page, the client downloads a whole *segment* of pages in one request.

This lets the client amortize network overhead and hydrate nearby pages that are likely to be accessed soon.

**How it works**

Suppose your database has:

* `page_size = 4 KiB`
* `segment_size = 16 KiB`

If a local query touches page **6**, the client computes the segment that page belongs to:

* 16 KiB segment = 4 pages
* Segment covering page 6 = pages **5-8**

The client then fetches all four pages in a single request and stores them locally.
Future reads to those pages incur no additional network cost.

**Benefits**

* Fewer HTTP requests (one segment fetch vs. many single-page fetches)
* Faster hydration of hot ranges
* Better performance for workloads with spatial locality (e.g., range scans, index lookups)

**Default**

The default `segment_size` is **128 KiB** (typically 32 pages on a 4 KiB page size), which provides a good balance between request overhead and total bytes transferred.

<Tip>
  If your workload touches data in tight clusters (e.g., reading several adjacent rows), larger segment sizes can significantly improve performance.

  Conversely, very sparse/random-access workloads may benefit from smaller segment sizes.
</Tip>

<CodeGroup>
  ```ts TypeScript theme={null}
  await connect({
    ...
    partialSyncExperimental: {
      bootstrapStrategy: { kind: 'prefix', length: 128 * 1024 }, // 128 KiB
      segmentSize: 16 * 1024,
    },
  });
  ```

  ```py Python theme={null}
  turso.sync.connect(
      ...
      partial_sync_opts=turso.sync.PartialSyncOpts(
          bootstrap_strategy=turso.sync.PartialSyncPrefixBootstrap(length=128 * 1024),
          segment_size=16 * 1024,
      ),
  )
  ```

  ```go Go theme={null}
  turso.NewTursoSyncDb(context.Background(), turso.TursoSyncDbConfig{
    ...
    PartialSyncConfig: turso.TursoPartialSyncConfig{
      BoostrapStrategyPrefix: 128 * 1024, // 128 KiB
      SegmentSize: 16 * 1024,
    },
  })
  ```
</CodeGroup>

### Prefetch

<Frame>
  <div id="prefetch-viz" style={{ padding: '1rem 0.5rem' }}>
    <style>
      {`
              #p1-cell-1, #p1-cell-2, #p1-cell-3, #p1-cell-4, #p1-cell-5, #p1-cell-6, #p1-cell-7, #p1-cell-8, #p1-cell-9, #p1-cell-10, #p1-cell-11, #p1-cell-12 { cursor: pointer; }
              #p1-cell-1:hover rect, #p1-cell-2:hover rect, #p1-cell-3:hover rect, #p1-cell-4:hover rect, #p1-cell-5:hover rect, #p1-cell-6:hover rect, #p1-cell-7:hover rect, #p1-cell-8:hover rect, #p1-cell-9:hover rect, #p1-cell-10:hover rect, #p1-cell-11:hover rect, #p1-cell-12:hover rect { filter: brightness(1.2); }
            `}
    </style>

    <svg viewBox="0 0 540 140" xmlns="http://www.w3.org/2000/svg" style={{ width: '100%', minWidth: '480px', maxWidth: '620px', display: 'block', margin: '0 auto' }}>
      <defs>
        <marker id="arrowPf" markerWidth="8" markerHeight="6" refX="8" refY="3" orient="auto">
          <polygon points="0 0, 8 3, 0 6" fill="#6b7280" />
        </marker>

        <marker id="arrowPrefetch" markerWidth="6" markerHeight="5" refX="6" refY="2.5" orient="auto">
          <polygon points="0 0, 6 2.5, 0 5" fill="#8b5cf6" />
        </marker>
      </defs>

      <g id="pf-state-1">
        <text x="76" y="14" fill="#9ca3af" fontFamily="ui-monospace,monospace" fontSize="10" textAnchor="middle">select page</text>

        {/* Row 1 */}

        <g id="p1-cell-1"><rect id="p1-rect-1" x="10" y="22" width="30" height="30" fill="#1ebca1" stroke="#1ebca1" strokeWidth="2" rx="4" /><text id="p1-text-1" x="25" y="42" fill="#0a0a0a" fontFamily="ui-monospace,monospace" fontSize="12" textAnchor="middle" fontWeight="bold" style={{ pointerEvents:'none' }}>1</text></g>
        <g id="p1-cell-2"><rect id="p1-rect-2" x="44" y="22" width="30" height="30" fill="#1ebca1" stroke="#1ebca1" strokeWidth="2" rx="4" /><text id="p1-text-2" x="59" y="42" fill="#0a0a0a" fontFamily="ui-monospace,monospace" fontSize="12" textAnchor="middle" fontWeight="bold" style={{ pointerEvents:'none' }}>2</text></g>
        <g id="p1-cell-3"><rect id="p1-rect-3" x="78" y="22" width="30" height="30" fill="#1ebca1" stroke="#1ebca1" strokeWidth="2" rx="4" /><text id="p1-text-3" x="93" y="42" fill="#0a0a0a" fontFamily="ui-monospace,monospace" fontSize="12" textAnchor="middle" fontWeight="bold" style={{ pointerEvents:'none' }}>3</text></g>
        <g id="p1-cell-4"><rect id="p1-rect-4" x="112" y="22" width="30" height="30" fill="#2a2a4a" stroke="#fbbf24" strokeWidth="3" rx="4" /><text id="p1-text-4" x="127" y="42" fill="#fbbf24" fontFamily="ui-monospace,monospace" fontSize="12" textAnchor="middle" fontWeight="bold" style={{ pointerEvents:'none' }}>4</text></g>

        {/* Row 2 */}

        <g id="p1-cell-5"><rect id="p1-rect-5" x="10" y="56" width="30" height="30" fill="#2a2a4a" stroke="#3a3a5a" strokeWidth="1" rx="4" /><text id="p1-text-5" x="25" y="76" fill="#6b7280" fontFamily="ui-monospace,monospace" fontSize="12" textAnchor="middle" style={{ pointerEvents:'none' }}>5</text></g>
        <g id="p1-cell-6"><rect id="p1-rect-6" x="44" y="56" width="30" height="30" fill="#2a2a4a" stroke="#3a3a5a" strokeWidth="1" rx="4" /><text id="p1-text-6" x="59" y="76" fill="#6b7280" fontFamily="ui-monospace,monospace" fontSize="12" textAnchor="middle" style={{ pointerEvents:'none' }}>6</text></g>
        <g id="p1-cell-7"><rect id="p1-rect-7" x="78" y="56" width="30" height="30" fill="#2a2a4a" stroke="#3a3a5a" strokeWidth="1" rx="4" /><text id="p1-text-7" x="93" y="76" fill="#6b7280" fontFamily="ui-monospace,monospace" fontSize="12" textAnchor="middle" style={{ pointerEvents:'none' }}>7</text></g>
        <g id="p1-cell-8"><rect id="p1-rect-8" x="112" y="56" width="30" height="30" fill="#2a2a4a" stroke="#3a3a5a" strokeWidth="1" rx="4" /><text id="p1-text-8" x="127" y="76" fill="#6b7280" fontFamily="ui-monospace,monospace" fontSize="12" textAnchor="middle" style={{ pointerEvents:'none' }}>8</text></g>

        {/* Row 3 */}

        <g id="p1-cell-9"><rect id="p1-rect-9" x="10" y="90" width="30" height="30" fill="#2a2a4a" stroke="#3a3a5a" strokeWidth="1" rx="4" /><text id="p1-text-9" x="25" y="110" fill="#6b7280" fontFamily="ui-monospace,monospace" fontSize="12" textAnchor="middle" style={{ pointerEvents:'none' }}>9</text></g>
        <g id="p1-cell-10"><rect id="p1-rect-10" x="44" y="90" width="30" height="30" fill="#2a2a4a" stroke="#3a3a5a" strokeWidth="1" rx="4" /><text id="p1-text-10" x="59" y="110" fill="#6b7280" fontFamily="ui-monospace,monospace" fontSize="12" textAnchor="middle" style={{ pointerEvents:'none' }}>10</text></g>
        <g id="p1-cell-11"><rect id="p1-rect-11" x="78" y="90" width="30" height="30" fill="#2a2a4a" stroke="#8b5cf6" strokeWidth="2" rx="4" /><text id="p1-text-11" x="93" y="110" fill="#8b5cf6" fontFamily="ui-monospace,monospace" fontSize="12" textAnchor="middle" fontWeight="bold" style={{ pointerEvents:'none' }}>11</text></g>
        <g id="p1-cell-12"><rect id="p1-rect-12" x="112" y="90" width="30" height="30" fill="#2a2a4a" stroke="#8b5cf6" strokeWidth="2" rx="4" /><text id="p1-text-12" x="127" y="110" fill="#8b5cf6" fontFamily="ui-monospace,monospace" fontSize="12" textAnchor="middle" fontWeight="bold" style={{ pointerEvents:'none' }}>12</text></g>

        {/* B-tree arrows drawn here by JS */}

        <g id="pf-btree-arrows" />
      </g>

      <g id="pf-arrow-1" style={{ transition: 'opacity 0.3s' }}>
        <line x1="152" y1="71" x2="188" y2="71" stroke="#6b7280" strokeWidth="2" markerEnd="url(#arrowPf)" />

        <text id="pf-arrow-label" x="170" y="64" fill="#8b5cf6" fontFamily="ui-monospace,monospace" fontSize="9" textAnchor="middle">read(4)</text>
      </g>

      <g id="pf-state-2" style={{ transition: 'opacity 0.3s' }}>
        <text x="268" y="14" fill="#f97316" fontFamily="ui-monospace,monospace" fontSize="10" textAnchor="middle">fetching</text>

        {/* Row 1 */}

        <g><rect id="p2-rect-1" x="203" y="22" width="30" height="30" fill="#1ebca1" stroke="#1ebca1" strokeWidth="2" rx="4" /><text id="p2-text-1" x="218" y="42" fill="#0a0a0a" fontFamily="ui-monospace,monospace" fontSize="12" textAnchor="middle" fontWeight="bold">1</text></g>
        <g><rect id="p2-rect-2" x="237" y="22" width="30" height="30" fill="#1ebca1" stroke="#1ebca1" strokeWidth="2" rx="4" /><text id="p2-text-2" x="252" y="42" fill="#0a0a0a" fontFamily="ui-monospace,monospace" fontSize="12" textAnchor="middle" fontWeight="bold">2</text></g>
        <g><rect id="p2-rect-3" x="271" y="22" width="30" height="30" fill="#1ebca1" stroke="#1ebca1" strokeWidth="2" rx="4" /><text id="p2-text-3" x="286" y="42" fill="#0a0a0a" fontFamily="ui-monospace,monospace" fontSize="12" textAnchor="middle" fontWeight="bold">3</text></g>
        <g><rect id="p2-rect-4" x="305" y="22" width="30" height="30" fill="#f97316" stroke="#fbbf24" strokeWidth="3" rx="4" /><text id="p2-text-4" x="320" y="42" fill="#0a0a0a" fontFamily="ui-monospace,monospace" fontSize="12" textAnchor="middle" fontWeight="bold">4</text></g>

        {/* Row 2 */}

        <g><rect id="p2-rect-5" x="203" y="56" width="30" height="30" fill="#2a2a4a" stroke="#3a3a5a" strokeWidth="1" rx="4" /><text id="p2-text-5" x="218" y="76" fill="#6b7280" fontFamily="ui-monospace,monospace" fontSize="12" textAnchor="middle">5</text></g>
        <g><rect id="p2-rect-6" x="237" y="56" width="30" height="30" fill="#2a2a4a" stroke="#3a3a5a" strokeWidth="1" rx="4" /><text id="p2-text-6" x="252" y="76" fill="#6b7280" fontFamily="ui-monospace,monospace" fontSize="12" textAnchor="middle">6</text></g>
        <g><rect id="p2-rect-7" x="271" y="56" width="30" height="30" fill="#2a2a4a" stroke="#3a3a5a" strokeWidth="1" rx="4" /><text id="p2-text-7" x="286" y="76" fill="#6b7280" fontFamily="ui-monospace,monospace" fontSize="12" textAnchor="middle">7</text></g>
        <g><rect id="p2-rect-8" x="305" y="56" width="30" height="30" fill="#2a2a4a" stroke="#3a3a5a" strokeWidth="1" rx="4" /><text id="p2-text-8" x="320" y="76" fill="#6b7280" fontFamily="ui-monospace,monospace" fontSize="12" textAnchor="middle">8</text></g>

        {/* Row 3 */}

        <g><rect id="p2-rect-9" x="203" y="90" width="30" height="30" fill="#2a2a4a" stroke="#3a3a5a" strokeWidth="1" rx="4" /><text id="p2-text-9" x="218" y="110" fill="#6b7280" fontFamily="ui-monospace,monospace" fontSize="12" textAnchor="middle">9</text></g>
        <g><rect id="p2-rect-10" x="237" y="90" width="30" height="30" fill="#2a2a4a" stroke="#3a3a5a" strokeWidth="1" rx="4" /><text id="p2-text-10" x="252" y="110" fill="#6b7280" fontFamily="ui-monospace,monospace" fontSize="12" textAnchor="middle">10</text></g>
        <g><rect id="p2-rect-11" x="271" y="90" width="30" height="30" fill="#f97316" stroke="#f97316" strokeWidth="2" rx="4" /><text id="p2-text-11" x="286" y="110" fill="#0a0a0a" fontFamily="ui-monospace,monospace" fontSize="12" textAnchor="middle" fontWeight="bold">11</text></g>
        <g><rect id="p2-rect-12" x="305" y="90" width="30" height="30" fill="#f97316" stroke="#f97316" strokeWidth="2" rx="4" /><text id="p2-text-12" x="320" y="110" fill="#0a0a0a" fontFamily="ui-monospace,monospace" fontSize="12" textAnchor="middle" fontWeight="bold">12</text></g>
      </g>

      <g id="pf-arrow-2" style={{ transition: 'opacity 0.3s' }}>
        <line x1="345" y1="71" x2="381" y2="71" stroke="#6b7280" strokeWidth="2" markerEnd="url(#arrowPf)" />
      </g>

      <g id="pf-state-3" style={{ transition: 'opacity 0.3s' }}>
        <text x="461" y="14" fill="#1ebca1" fontFamily="ui-monospace,monospace" fontSize="10" textAnchor="middle">loaded</text>

        {/* Row 1 */}

        <g><rect id="p3-rect-1" x="396" y="22" width="30" height="30" fill="#1ebca1" stroke="#1ebca1" strokeWidth="2" rx="4" /><text id="p3-text-1" x="411" y="42" fill="#0a0a0a" fontFamily="ui-monospace,monospace" fontSize="12" textAnchor="middle" fontWeight="bold">1</text></g>
        <g><rect id="p3-rect-2" x="430" y="22" width="30" height="30" fill="#1ebca1" stroke="#1ebca1" strokeWidth="2" rx="4" /><text id="p3-text-2" x="445" y="42" fill="#0a0a0a" fontFamily="ui-monospace,monospace" fontSize="12" textAnchor="middle" fontWeight="bold">2</text></g>
        <g><rect id="p3-rect-3" x="464" y="22" width="30" height="30" fill="#1ebca1" stroke="#1ebca1" strokeWidth="2" rx="4" /><text id="p3-text-3" x="479" y="42" fill="#0a0a0a" fontFamily="ui-monospace,monospace" fontSize="12" textAnchor="middle" fontWeight="bold">3</text></g>
        <g><rect id="p3-rect-4" x="498" y="22" width="30" height="30" fill="#1ebca1" stroke="#fbbf24" strokeWidth="3" rx="4" /><text id="p3-text-4" x="513" y="42" fill="#0a0a0a" fontFamily="ui-monospace,monospace" fontSize="12" textAnchor="middle" fontWeight="bold">4</text></g>

        {/* Row 2 */}

        <g><rect id="p3-rect-5" x="396" y="56" width="30" height="30" fill="#2a2a4a" stroke="#3a3a5a" strokeWidth="1" rx="4" /><text id="p3-text-5" x="411" y="76" fill="#6b7280" fontFamily="ui-monospace,monospace" fontSize="12" textAnchor="middle">5</text></g>
        <g><rect id="p3-rect-6" x="430" y="56" width="30" height="30" fill="#2a2a4a" stroke="#3a3a5a" strokeWidth="1" rx="4" /><text id="p3-text-6" x="445" y="76" fill="#6b7280" fontFamily="ui-monospace,monospace" fontSize="12" textAnchor="middle">6</text></g>
        <g><rect id="p3-rect-7" x="464" y="56" width="30" height="30" fill="#2a2a4a" stroke="#3a3a5a" strokeWidth="1" rx="4" /><text id="p3-text-7" x="479" y="76" fill="#6b7280" fontFamily="ui-monospace,monospace" fontSize="12" textAnchor="middle">7</text></g>
        <g><rect id="p3-rect-8" x="498" y="56" width="30" height="30" fill="#2a2a4a" stroke="#3a3a5a" strokeWidth="1" rx="4" /><text id="p3-text-8" x="513" y="76" fill="#6b7280" fontFamily="ui-monospace,monospace" fontSize="12" textAnchor="middle">8</text></g>

        {/* Row 3 */}

        <g><rect id="p3-rect-9" x="396" y="90" width="30" height="30" fill="#2a2a4a" stroke="#3a3a5a" strokeWidth="1" rx="4" /><text id="p3-text-9" x="411" y="110" fill="#6b7280" fontFamily="ui-monospace,monospace" fontSize="12" textAnchor="middle">9</text></g>
        <g><rect id="p3-rect-10" x="430" y="90" width="30" height="30" fill="#2a2a4a" stroke="#3a3a5a" strokeWidth="1" rx="4" /><text id="p3-text-10" x="445" y="110" fill="#6b7280" fontFamily="ui-monospace,monospace" fontSize="12" textAnchor="middle">10</text></g>
        <g><rect id="p3-rect-11" x="464" y="90" width="30" height="30" fill="#1ebca1" stroke="#1ebca1" strokeWidth="2" rx="4" /><text id="p3-text-11" x="479" y="110" fill="#0a0a0a" fontFamily="ui-monospace,monospace" fontSize="12" textAnchor="middle" fontWeight="bold">11</text></g>
        <g><rect id="p3-rect-12" x="498" y="90" width="30" height="30" fill="#1ebca1" stroke="#1ebca1" strokeWidth="2" rx="4" /><text id="p3-text-12" x="513" y="110" fill="#0a0a0a" fontFamily="ui-monospace,monospace" fontSize="12" textAnchor="middle" fontWeight="bold">12</text></g>
      </g>
    </svg>

    <p id="pf-status" style={{ textAlign: 'center', color: '#f97316', fontSize: '0.8rem', margin: '0.5rem 0 0', fontFamily: 'ui-monospace, monospace', transition: 'color 0.3s' }}>
      Read page 4 → prefetch 2 child pages (11, 12)
    </p>
  </div>
</Frame>

Prefetch is an optional optimization that builds on top of lazy page fetches.
When enabled, the client not only retrieves the pages required by the current query, but also **inspects the structure of the newly downloaded pages and recent access patterns** to predict which pages are likely to be needed next.

If the client detects a natural continuation of the access pattern — such as child pages referenced by an internal B-tree node — it proactively downloads those pages in advance.
This reduces the number of future on-demand fetches and helps avoid stalls during operations like range scans, index walks, or sequential lookups.

<CodeGroup>
  ```ts TypeScript theme={null}
  await connect({
    ...
    partialSyncExperimental: {
      bootstrapStrategy: { kind: 'prefix', length: 128 * 1024 }, // 128 KiB
      prefetch: true,
    },
  });
  ```

  ```py Python theme={null}
  turso.sync.connect(
      ...
      partial_sync_opts=turso.sync.PartialSyncOpts(
          bootstrap_strategy=turso.sync.PartialSyncPrefixBootstrap(length=128 * 1024),
          prefetch=True,
      ),
  )
  ```

  ```go Go theme={null}
  turso.NewTursoSyncDb(context.Background(), turso.TursoSyncDbConfig{
    ...
    PartialSyncConfig: turso.TursoPartialSyncConfig{
      BoostrapStrategyPrefix: 128 * 1024, // 128 KiB
      Prefetch: true,
    },
  })
  ```
</CodeGroup>

<Note>
  `segment_size` and `prefetch` are complementary.

  Segment size batches nearby pages into a single on-demand fetch, while prefetch looks at the query's access pattern and proactively fetches additional pages likely to be needed next.

  Using both together can provide the best performance for real-world workloads.
</Note>
> ## Documentation Index
> Fetch the complete documentation index at: https://docs.turso.tech/llms.txt
> Use this file to discover all available pages before exploring further.

# Conflict Resolution

> How Turso sync handles concurrent changes from multiple clients.

<Note>
  This particular usage uses the Turso Cloud to sync the local Turso databases and assumes that you have an account.
</Note>

## Last Push Wins

Turso sync uses a **last push wins** strategy. When two clients modify the same data and push, the last push determines the final state on the remote.

| Time | Client A                                   | Client B                                 |
| ---- | ------------------------------------------ | ---------------------------------------- |
| T1   | `UPDATE users SET name='Alice' WHERE id=1` |                                          |
| T2   |                                            | `UPDATE users SET name='Bob' WHERE id=1` |
| T3   | `push()`                                   |                                          |
| T4   |                                            | `push()`                                 |

**Result**: The name is `'Bob'` because Client B pushed last.

## What Happens During Pull

When you pull and have unpushed local changes:

1. Your local database is rolled back to the last synced state
2. Remote changes are applied
3. Your unpushed local changes are **replayed** on top

This rollback-and-replay happens atomically — if anything fails, your database remains in its previous state.
> ## Documentation Index
> Fetch the complete documentation index at: https://docs.turso.tech/llms.txt
> Use this file to discover all available pages before exploring further.

# Checkpoint

> How to compact the local WAL to bound disk usage while preserving sync state.

<Note>
  This particular usage uses the Turso Cloud to sync the local Turso databases and assumes that you have an account.
</Note>

## Overview

The sync engine uses a WAL (Write-Ahead Log) to track local writes. Over time, the WAL grows as you make changes. Checkpoint compacts it by transferring committed frames into the main database file and then truncating the WAL.

Auto-checkpoint is **disabled** for sync databases — you must call `checkpoint()` explicitly.

## Why Checkpoint Matters

Without checkpointing, the WAL grows unbounded. After many writes, the WAL can become significantly larger than the database itself. Checkpointing reclaims that disk space.

You can observe this with `stats()`:

<CodeGroup>
  ```ts TypeScript theme={null}
  const before = await db.stats();
  console.log('WAL size before:', before.mainWalSize);

  await db.checkpoint();

  const after = await db.stats();
  console.log('WAL size after:', after.mainWalSize);
  ```

  ```py Python theme={null}
  before = conn.stats()
  print("WAL size before:", before.main_wal_size)

  conn.checkpoint()

  after = conn.stats()
  print("WAL size after:", after.main_wal_size)
  ```

  ```go Go theme={null}
  before, _ := db.Stats(ctx)
  log.Printf("WAL size before: %d", before.MainWalSize)

  db.Checkpoint(ctx)

  after, _ := db.Stats(ctx)
  log.Printf("WAL size after: %d", after.MainWalSize)
  ```
</CodeGroup>

## When to Checkpoint

Call `checkpoint()` periodically based on your write patterns:

* **After bulk inserts** — if you insert many rows at once, checkpoint afterward to reclaim WAL space
* **On a schedule** — for steady write workloads, checkpoint at regular intervals (e.g. every few minutes)
* **When WAL size is large** — use `stats().mainWalSize` to monitor and checkpoint when it exceeds a threshold

<CodeGroup>
  ```ts TypeScript theme={null}
  await db.checkpoint();
  ```

  ```py Python theme={null}
  conn.checkpoint()
  ```

  ```go Go theme={null}
  if err := db.Checkpoint(ctx); err != nil {
  	return err
  }
  ```
</CodeGroup>
