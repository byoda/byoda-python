# byoda-python

Reference Python implementation of the Byoda network: a personal-data-store platform where users own their data in a pod, services are defined by signed data contracts, and a directory + service infrastructure runs the network. The repo currently hosts five servers plus a shared library; a planned split will divide it into multiple repos.

## Language

### Servers and runtimes

**Pod**:
The user-owned personal data store. Implemented today by `podserver/` and the byoda-library code it depends on. Runs on user-controlled infrastructure (home server or public cloud VM).
_Avoid_: "Personal server", "user node", "data node"

**BYO.Tube Service** (`byotubesvr`):
The centrally-hosted SaaS service that runs the BYO.Tube application on top of the Byoda network. Holds lite accounts, asset reactions, network links, and runs background workers.
_Avoid_: "Tube server", "service server" (ambiguous — see below)

**Network Infrastructure**:
The set of central services that operate the byoda.net network itself: the **Directory Server** (`dirserver/`), the generic **Service Server** (`svcserver/`), and the **App Server** (`appserver/`). Operated by the network owner.
_Avoid_: "Backend", "infra" alone

**Service Server**:
The generic per-service FastAPI server that any service definition runs against. Hosts member registry, search, app registration. Distinct from "BYO.Tube Service", which is a specific service implementation.
_Avoid_: "Service" alone (ambiguous — could mean the service definition, the running server, or the BYO.Tube product)

### Code organisation

**byoda-library** / **`byoda/`**:
The shared Python library under `byoda/` that all five servers depend on today. Contains PKI, data-contract handling, storage abstractions, request auth, common datatypes, and (currently) some misplaced server-specific and pod-specific code.
_Avoid_: "Common", "shared", "core" (until decoupled — see "byoda-core" below)

**byoda-core** (proposed):
The post-decoupling shape of `byoda/`: PKI, data-contract handling (schemas, dataclasses, filters), storage backends, request auth, common datatypes, common API models, common utilities. Excludes any code used by only one target repo.
_Avoid_: "Common library", "shared lib"

**Decouple-first**:
The agreed approach: before splitting the repo, move all single-consumer code out of `byoda/` into the server that uses it, shrinking the library to its genuinely-shared core. Only then split.

### Data-contract concepts (carried over from existing code)

**Service Contract** / **Data Contract**:
A signed JSON Schema document that defines the data model, access-control rules, and APIs for a service. Pods read the contract and auto-generate Data APIs.
_Avoid_: "Schema" alone (overloaded — JSON Schema, the contract, and the generated data model are all called this in places)

**Member**:
The identity a pod takes within a specific service after joining it. A pod can hold many memberships, one per joined service.
_Avoid_: "User", "Account" (Account is the pod-level identity, not the service-scoped one)

**Account**:
The pod-level identity, distinct from the service-scoped Member identity.
_Avoid_: "User", "Owner"

### Repo-split target

**Three-repo split** (planned):
- **pod repo**: today's `podserver/` plus its decoupled byoda code
- **byotubesvr repo**: today's `byotubesvr/`
- **network-infra repo**: `dirserver/` + `svcserver/` + `appserver/`, plus dirserver/svc-specific decoupled byoda code

**byoda-core repo** (planned, fourth):
The decoupled shared library, published as a Python package that the three service repos pin.

## Flagged ambiguities

- **"Service"** is used for: a Service Contract (the JSON Schema), the generic Service Server (`svcserver/`), and the BYO.Tube product. Disambiguate at use site.
- **"Schema"** is used for: the JSON Schema spec, the Service Contract document, and the Pydantic models generated from a contract. Disambiguate at use site.

## Example dialogue

> Dev: "I want to add a field to the asset model."
> Lead: "Are you adding it to the Service Contract for BYO.Tube, or to a Pydantic model in `byoda/models/`?"
> Dev: "The contract. The pod should pick it up automatically."
> Lead: "Then it's a BYO.Tube Service Contract change — bump the contract version, sign it, and the Pod will regenerate its Data APIs from the new contract when it next joins or refreshes."
> Dev: "And the BYO.Tube Service needs the field too — it caches assets."
> Lead: "Right, the BYO.Tube Service reads from pods over the Data API, so once the Pod exposes the field, the Service can pick it up. No `byoda-core` change needed unless the Pydantic representation of an asset cache row needs updating."
