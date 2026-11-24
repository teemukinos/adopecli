# Material development contract

Dobe Material uses the maintained CPU engine built from MaterialCraft v0.4.1,
revision `65f7bfd3e5f40d695d03162285879f0f8079ff6c`. This is a clean-room native
procedural material designer. Its editable documents are SBS XML and `.mcraft`
archives containing SBS and embedded resources. The actual private CLI enumerates 29 primitive/input/output entries. Native
function and pattern graph operations remain separate catalogs. The upstream
documentation claims 30 main-graph entries; this pin exposes 29 through `nodes`. Earlier upstream claims of hundreds of
native procedural nodes predate a library rewrite and do not describe this pin.

## Maintained source boundary

The opt-in `dobe` feature builds a separately named `dobe-material` executable.
It refuses standalone MCP, network serving, editor bridges, ports and tokens
before connection or token lookup. Customer operations belong to the existing
Dobe runtime and product MCP. Native CPU cooking and rendering require no paid
model service. The private native executable remains a trusted implementation
component, not an untrusted-input sandbox.

Automatic SBS library discovery is disabled. The upstream converted
`assets/sbs/functions.sbs` package is neither embedded nor loaded: the pinned
architecture, roadmap and gap documents explicitly leave redistribution rights
for its retained source bodies unverified. Native primitive/function operations
remain available. Original reusable production graphs are now provided by the versioned recipe
catalog below. Immutable archived dependencies now use the qualified contract described at the end of this document; ambient libraries remain disabled.

Saved external package references cannot trigger automatic file reads. Resource
loading callbacks are disabled for native opens; resources must be embedded in
an admitted document/archive. Recovered or unsupported imports with warnings,
missing resources and unowned external package instances are refused before publication
into a native session. Admitted archive members resolve through stable in-memory identities. Direct private-native `.mcmat` opening remains refused. The typed product import
now owns the admitted portable-material route described below. Explicit portable material export remains a private
native operation. Publication into the user's shared Texture library is refused;
a managed cross-application job must own that handoff.

Private `info` additionally returns the complete serialized native package model
for independent preservation checks. This does not establish that every original
XML field was interpreted or retained. XML/archive admission, unknown-field
handling, schema semantics, graph recursion/work limits and complete field/asset
preservation must be established before exposing public import or revision.

## Remaining runtime and release requirements

Typed creation, inspection, graph/parameter revision and bounded cooking now run
through durable jobs. Map export and CPU preview use the same bounded evaluator. Managed portable-material export/import and Texture handoff are described below.
Immutable archived-dependency handoff is qualified in the source runtime. Preserve stable node/graph selectors, original
inputs, approved surrounding state and editable
portable sources. Validate native errors and cold results independently; a native
process exit alone is insufficient. Bound complete document allocation and graph
execution, including function and pattern graphs and nested instances.

Unsigned dev.45 now qualifies installed CLI/MCP operations, cancellation,
supervisor-crash recovery and rollback/reinstall on the development Mac. It
contains twelve of seventeen required applications, including Material. Linux/Cloud, clean-machine,
reboot, signing and complete visual-fidelity qualification remain open. No native
full-CI, reference-renderer parity or arbitrary SBS interoperability is claimed.

## Current native evidence

The maintained native check passes 46 checks across 40 process calls. It verifies
six 64×64 PBR maps against independent exact pixel values, a base-color-only
revision preserving all other native fields and five unrequested map files,
complete cold archive reopening, repeatable CPU sphere previews, and a function/
pattern graph with nonuniform output that survives cold reopen. Portable material
export retains six maps and the revised editable SBS source. Connection, ambient
library, saved external package/resource, unsupported import and shared-library
publication refusals run against the actual binary. An imported PNG retains its exact bytes inside the native archive; its resource
fields and unrelated maps survive cold reopen. Original inputs remain unchanged.

The source-built package is separate from the installed eleven-app candidate.
Its 26 distributed files and 31 patched source files match the maintained
lock and manifest. CPU-only macOS ARM64 compilation succeeds offline with the
existing approved Cargo cache; no remote tests or other remote actions run.
The small native fixtures do not establish production compute cost or general
material quality. Full native CI and arbitrary imported-document fidelity remain
unqualified.

```sh
python3 -B craft/tests/material_native_check.py --engine /path/to/dobe-material \
  --output /path/to/new-native-evidence
```

## Bounded SBS and archive snapshots

`material_container` snapshots bare UTF-8 SBS or MCraft archives without extracting
files, following dependencies or invoking the engine. It reuses the qualified ZIP
header/directory primitives while adding ordinary directory support and refusing
case-colliding names and file/descendant conflicts. Stored/deflated and bounded
native ZIP64 members are supported. Complete payload intervals, checksums and
compression streams must agree; hidden preambles, gaps, trailers, special files,
ambiguous paths and duplicate members are refused.

Limits are 256 MiB of source and expanded archive bytes, 64 MiB per non-SBS
member, 4,096 entries and 2 MiB of ZIP directory data. SBS XML has a 32 MiB
aggregate limit, 250,000 aggregate content nodes, 64 nesting levels and at most
128 attributes per element. Parser callbacks check limits before adding nodes.
DTDs, external entities, namespaces, alternate encodings and malformed XML are
refused. Unknown elements, attributes, comments and processing instructions remain
inventoried alongside exact original bytes. Their presence is not permission to
execute a native document.

SBS compressed embedded resources use the native big-endian length prefix,
canonical base64 and one complete zlib stream. Expansion is limited to 64 MiB per
resource and 128 MiB in total. Redundant `datalength` metadata must agree when
present; duplicate declarations and trailing compressed data are refused. Image
format validation and decoded-image budgets remain separate prerequisites.

`check_preservation` compares the complete directory/member inventory and every
exact decompressed member byte. ZIP compression and timestamps can differ. An
edit or representation conversion requires its own explicitly predicted change;
the helper never normalizes unexpected content to make a comparison pass.

The container check passes 108 checks, including five actual native documents and
1,000 deterministic ZIP mutations. Seventy-five mutations remain valid and agree
with an independent ZIP decoder; 925 refuse. Native preservation checks cover
five cold-reopened files, an actual compressed embedded image and three explicit
counterexamples. The native engine silently drops an unknown archive member and
an unknown XML attribute while returning success; complete preservation detects
both. Saving an embedded bare SBS produces adjacent resource files and changed
XML. This is a representation conversion, not a claim of lost image bytes; it
also requires an explicit conversion contract. Every original input is retained.

These checks do not establish semantic graph admission, execution budgets,
resource-reference completeness, imported-document fidelity or public runtime
availability. All reports retain `engine_admission_complete: false`.

```sh
python3 -B craft/tests/material_container_check.py --native /path/to/native.mcraft \
  --evidence /path/to/new-container-evidence.json
python3 -B craft/tests/material_preservation_check.py --engine /path/to/dobe-material \
  --fixtures /path/to/retained-native-evidence --output /path/to/new-preservation-evidence
```

## Package and bitmap-resource admission

`material_resources` validates package metadata, dependency declarations, folders,
item identities and resource declarations against the retained XML snapshot.
Duplicate identities, missing fields, unknown package/resource fields, conflicting
resource sources and legacy fallback paths refuse. Archived dependencies resolve
only to already inventoried SBS members. Bare SBS cannot request adjacent files,
and aliases/URLs cannot introduce ambient libraries. Every archive file must be
accounted for by the root, declared packages or resources. Graph bodies remain
opaque at this stage and require their own complete semantic validation.

Limits are 64 packages, 4,096 package items, 256 resources, 128 MiB of resource
bytes and 33,554,432 decoded resource texels. Repeated resource references count
separately toward allocation. Eight bitmap profiles reuse the qualified complete
image decoders: PNG, JPEG, TGA, TIFF, BMP, WebP, flat RGB(A) EXR and Radiance HDR.
Declared format must agree with decoded bytes. Original bytes and hashes remain
available for independent native comparison. SVG, DDS, GIF, PGM and additional
image profiles require separate qualification; they are not silently converted.

Native resource inventory must agree on names, folders, file identities, byte
counts and missing status. Inventory agreement alone does not prove decoding:
the native check connects each tested resource to an actual bitmap node and PBR
output, verifies its cook and independently checks exported color pixels. Cold
reopen must preserve every native member byte and the original imported image.

The resource check passes 84 checks across fifty native calls. All eight bitmap
profiles pass actual decoding, pixel agreement and complete cold preservation.
Tests also cover nested archive dependency inventory, compressed embedded SBS
resources, malformed identities/references, unknown members, aggregate limits
and deliberately inconsistent native reports. Compound package/resource identities
use unambiguous pairs, including when legal names contain delimiter characters.

A reproduced decoder disagreement needs an additional guard: the native decoder
interprets UTF-8 text containing `<svg` in its first 4,096 bytes as SVG. A valid HDR
with sufficiently long ASCII comments can trigger that branch. Independent HDR
decoding succeeds, but actual native import fails before publication. Resource
admission now rejects this ambiguous profile before invoking the native decoder.

Handwritten archive resource filenames are not canonical native filenames:
native save changes them to content-addressed names. The first qualification
fixture exposed that conversion and was retained. Successful cold-preservation
fixtures are now authored through actual native bitmap import. No preservation
check was weakened to permit unplanned renaming.

This remains a prerequisite, not a registered operation. Full graph, function,
pattern, reference and work-budget admission, explicit conversion, typed durable
jobs and installed qualification remain open.

```sh
python3 -B craft/tests/material_resources_check.py --engine /path/to/dobe-material \
  --fixtures /path/to/retained-native-evidence \
  --embedded-source /path/to/portable-resource.sbs --output /path/to/new-evidence
```

## Procedural bodies and local work accounting

`studio_runtime.material_procedural` validates embedded function and FX-Map
pattern bodies before native opening. It preserves the original container/XML
bytes and builds an independent structural model. It does not authorize native
execution: outer image graphs, type/scope semantics, instance resolution,
per-pixel evaluation, raster work and whole-job limits remain required.

The connector catalog covers all 85 intrinsic operations in the pinned source.
Its provenance records the source revision and SHA-256; no converted library
function bodies are included. Function schemas check exact fields, scalar and
vector arity, finite binary32 values, signed native integer ranges, native u32
node IDs, unique ports and identities, explicit serialized settings and result
references. An iterative topology check includes unreachable components, rejects
cycles and missing sources, and handles a 4,096-node chain without Python
recursion. Incomplete editable graphs remain distinguishable from executable
ones. A Dot result that the native reader would silently remove is refused.

All four pattern node kinds have explicit connector and parameter contracts.
Pattern data must be referenced exactly once, have matching types and include
serialized defaults. Unknown parameters, duplicate data, ignored relative modes,
missing references and out-of-range constant iteration counts refuse. Dynamic
parameter functions use the same validator. Frames, comments and pins retain
their source fields; unsupported canvas fields and values that would be clamped
or discarded refuse. Canvas validation is separate from the normalized noncanvas
procedural model.

Function call references preserve graph paths and explicit interfaces. They do
not follow files, ambient libraries or URLs. Reports mark calls as requiring
resolution; dependency identity, call depth, recursion, input defaults and output
types must be checked against admitted packages before execution.

The local work estimator counts repeated paths through shared DAGs rather than
only unique nodes. It conservatively counts function branches, stateful sequences
and loop iterations, saturating at the native 100,000-step execution ceiling.
Negative loop limits retain that ceiling and explicitly report possible budget
exhaustion; this does not prove termination or a successful result. Pure-node
caching may reduce actual work. Pattern bounds count visits and stamps through
branches and repeated child paths, including the native 10,000-iteration limit
and 65,536-visit ceiling. Dynamic iteration counts remain marked. Multiplication
by image texels, stamp raster area, function invocations and graph instances is
still required for a complete job estimate.

Admission limits are 4,096 nodes per body, 256 bodies, 16,384 total procedural
nodes and 64 KiB per string. Aggregate body/node counts are checked before model
construction. All reports keep `engine_admission_complete: false`.

The offline check passes 101 checks across 22 native calls. It covers every
intrinsic connector through actual native parse,
serialization and exact cold member preservation. This is schema coverage, not
numeric qualification of all 85 operations. Independent value oracles execute
arithmetic, branches, stateful sequencing, bounded and immediately terminating
unbounded loops, vector assembly, swizzling, casts, missing-image sampling and a
same-package function call. All four pattern kinds cook in the actual CPU engine.
Three embedded canvas forms match independently expected native fields and
survive exact cold preservation. Adversarial tests cover ignored fields, malformed
values, identity/reference failures, cycles, compound bodies and allocation/work
limits. Original fixtures remain unchanged.

```sh
python3 -B craft/tests/material_procedural_check.py \
  --engine /path/to/dobe-material --fixture /path/to/atomic.mcraft \
  --upstream /path/to/pinned-material-source --output /path/to/new-evidence
```

## Outer image graphs, interfaces and native label preservation

`studio_runtime.material_graphs` validates the outer image/function graph schemas
and predicts native node identities, positions and wire topology. Its pinned
catalog records all 29 native node definitions and 25 SBS filter mappings, with
source/build provenance and the upstream MIT notice. Native `nodes` output must
match the recorded defaults, connectors and enum choice counts.

Validation covers graph metadata, parent sizes, all six base parameter types and
inheritance modes, graph inputs/outputs, exposed control metadata, preview
bindings, root outputs, native filter values, image/value bridges, instance
interfaces, curves, gradients, procedural bodies and annotations. Duplicate or
ignored fields, lossy enum/size conversion, mismatched defaults, unreferenced
bridges, aliased duplicate connectors, invalid port indices and missing wire
sources refuse. Topology includes disconnected components. Image input slots
are qualified through index 255. Aggregate limits are 256 graphs, 16,384 image
nodes, 4,096 ports per graph interface/node output and 4,096 cells per array.

Qualification exposed a real native fidelity defect: a graph output's custom
label was read without warnings and discarded on save. The maintained Dobe
source patch now restores the label on the output node. An independent revision
oracle proves that the label is the only changed native field. Native-authored
archives then retain every member byte across cold reopening. The earlier loss
counterexample remains recorded; the new behavior supersedes that restriction.
Empty serialized labels still require explicit conversion to the identifier
fallback. The upstream default build retains its original behavior.

The graph check passes 71 checks across 25 native calls. Actual native authoring
covers every node definition and both graph kinds.
Additional evidence covers twelve exposed controls (all ten value types,
dropdown choices and displayed color), all six base parameter types, exact native
node/wire agreement, the last indexed image input, custom label preservation and
complete cold native model/member agreement. Numeric execution of all 29 node
kinds is not implied by serialization coverage; existing independent PBR and
procedural execution oracles remain separate evidence.

This is still a prerequisite. Full parameter semantics, scope/type compatibility,
resource/preview targets, graph and function call resolution, recursion limits,
per-node inherited dimensions, raster work, aggregate execution budgets and
typed durable operations remain required. The topology comparison intentionally
does not claim complete parameter comparison or standalone preservation proof.
All reports retain `engine_admission_complete: false`.

```sh
python3 -B craft/tests/material_graphs_check.py --engine /path/to/dobe-material \
  --fixtures /path/to/retained-native-evidence --upstream /path/to/pinned-source \
  --output /path/to/new-evidence
```

## Owned references and bounded call expansion

`studio_runtime.material_references` resolves image/function calls, explicit
bitmap references and preview bindings entirely within admitted package snapshots.
A dependency UID must identify an admitted archive member; a saved path never
permits a filesystem or network read. Canonical decimal UID spelling prevents
numeric preflight identities from disagreeing with native string-based lookups.
Image graph references require exact graph paths. Function calls also support
the native unique-leaf alias rule, with exact paths taking precedence; ambiguous
aliases refuse.

Function interfaces must match source input names, ordering and native type
codes. Connected arguments must match those declared types; unconnected inputs
retain the source's default specifications for later numeric conversion. The
resolver predicts serialized instance metadata and result types, while keeping
full operand/scope checking distinct from native type inference. Unused empty
function graphs remain editable, but a called function must have a typed result.
Image instances must match source outputs and their declared types, use declared
inputs and override only exposed parameters. Resource references resolve to exact
owned resource identities. Cross-package bitmap references require an explicit
conversion because the pinned reader otherwise ignores the dependency component.

All graph components are checked for recursion, including disconnected calls.
Image and function call chains independently allow at most eight levels. Expanded
functions allow 4,096 nodes; expanded image graphs allow 16,384 nodes. Counts
include every call occurrence, including repeated calls to the same body, and
saturate before any call tree is materialized. These are structural expansion
bounds, not complete compute estimates or numeric termination guarantees.

Admitted archived calls retain `requires_external_handoff: true` as a structural
classification. The immutable handoff section below supersedes the original
execution hold. The native ambient-loader refusal remains in place until a managed immutable dependency
handoff is implemented and qualified. Successful snapshot resolution does not
turn that loader on, authorize execution or claim Cloud availability.

A second real fidelity defect was found while qualifying aliases and folders:
the prior reader traversed sibling folders in reverse order, so their serialized
order flipped on every cold save. The maintained Dobe reader now uses a queue
that preserves sibling order; upstream default traversal remains unchanged.
The original failure is retained. Exact cold member preservation now passes with
multiple same-named function graphs in different folders, without sorting or
normalizing the compared output bytes.

The reference check passes 72 checks across 26 native calls. Actual native
evidence covers defaulted and connected function calls, repeated
calls, eight-level function and image chains, unique aliases and exact-path
precedence, six independent PBR pixel oracles through image instances, and owned
preview-image pixels. References across admitted archive members resolve without
native opening and retain the explicit handoff gate. Negative cases include
recursion, a ninth call level, interface/type drift, absent or ambiguous targets,
missing resources and exhausted expansion budgets. All original fixtures remain
unchanged. Full value/scope semantics, inherited dimensions, raster/function work,
complete predicted native fields and durable runtime integration remain required.
Every report keeps `engine_admission_complete: false`.

```sh
python3 -B craft/tests/material_references_check.py --engine /path/to/dobe-material \
  --fixtures /path/to/retained-native-evidence \
  --resource-fixture /path/to/png-bitmap.mcraft --output /path/to/new-evidence
```

## Function operand contracts and numeric widget defaults

`material_function_semantics.inspect_function` checks a resolved function in its
actual caller scope: node parameters, pixel processing or FX-Map processing.
Reachable instructions require complete inputs, compatible numeric families and
dimensions, Boolean control conditions, matching branch/loop result types, valid
swizzle indices, legal casts and declared result types. Both possible control
paths are checked. Incomplete disconnected drafts stay editable and are excluded
from execution checks. The graph walk is iterative at the 4,096-node limit.

All twelve system variables have explicit type and scope contracts. `$pos` is
available to pixel and FX-Map functions; depth/number variables require FX-Map.
`isdefined` may query an unavailable variable and return false. User-variable
reads/writes remain explicit flow obligations. Callees require inspection in the
same caller scope; resolving a call does not establish its value semantics.

Qualification passes 449 checks across 121 native calls and executes all 85
intrinsic operations with independent numeric oracles, rather than claiming
numeric coverage from successful serialization.
Additional cases cover integer vectors, scalar/vector multiplication and
interpolation, invalid operands, scope violations, numeric overflow and drafts.
Static type success never certifies finite numeric results, ordered variable
flow, concrete native value variants or bounded complete job execution.

Two actual widget-default failures were reproduced in the preceding binary.
An enum default declared as Integer failed a numeric cast with `expected integer,
got enum`. An opaque black color default declared as Float4 compared unequal to
the identical numeric Float4 constant without an error. The maintained Dobe
getter now converts Enum to checked Integer and Color to Float4 at the function
boundary. Editable document defaults retain their Enum/Color variants, labels,
choices and color interpretation. Non-Dobe builds keep upstream behavior.
The default qualification passes 41 checks across 16 native calls. Defaulted and
connected calls produce the same independently expected numeric results and
retain every archive member byte after cold reopening.

These are prerequisites, not public runtime availability. Numeric conversion
ranges, concrete values, variable flow, inherited dimensions, context propagation,
per-pixel/pattern work and aggregate execution still need complete admission.
Reports retain `engine_admission_complete: false`.

```sh
python3 -B craft/tests/material_function_semantics_check.py \
  --engine /path/to/dobe-material --fixture /path/to/atomic.mcraft \
  --output /path/to/new-semantics-evidence
python3 -B craft/tests/material_function_defaults_check.py \
  --engine /path/to/dobe-material --fixture /path/to/atomic.mcraft \
  --output /path/to/new-defaults-evidence
```

## Base parameters and inherited dimensions

`material_base` independently predicts the native records and resolved values of
all six base parameters: output size, random seed, format, pixel size, pixel
ratio and tiling. It preserves absolute, input-relative and parent-relative
modes, the native Inherit format sentinel, wrapping unsigned seed arithmetic,
binary32 pixel products, and native size/pixel-size clamps. Root graph seeds use
the pinned engine's seed mixing; called graphs inherit their instance context.

Image inheritance follows native port order. Blend uses only its background;
an absent background falls back to the parent instead of the foreground.
Generators replace inherited dimensions with the parent dimensions while
retaining other inherited fields. Pixel processors inherit input dimensions.
Indexed image ports use numeric port order even when wires appear in another
order. Typed values cannot silently duplicate a generated image connector.

Resolved bases remain distinct from raster dimensions. Preview limits cap the
raster dimensions without rewriting inherited bases. The actual child Value
Processor in a qualified graph instance receives a capped 512×128 evaluation
context while its inherited base stays 1024×256; the saved child size is 16×16.
The prediction matches this distinction. Parameter functions use their own
native evaluation order and changing contexts, which still require a qualified
function evaluator.

Dynamic base functions never fall back to guessed literal dimensions. Resolution
requires complete, explicitly supplied qualified values and validates their
native types/ranges. The current check supplies independently known constant
function results; it does not constitute a general dynamic evaluator. Recursive
call layout, actual output-kind dimensions, total image allocation, pattern
raster work and whole-job budgets remain separate requirements.

Qualification passes 471 checks across 28 native calls. It covers all 29 node
definitions, all six literal and dynamic base types, inherited port behavior,
seed overflow, fractional binary32 values, clamp extremes, preview rounding,
an actual owned graph call and detection of a changed native base result.
All original inputs remain unchanged. Reports retain
`engine_admission_complete: false`; Material is still not registered in dev.44.

```sh
python3 -B craft/tests/material_base_check.py --engine /path/to/dobe-material \
  --fixtures /path/to/retained-native-evidence \
  --catalog-fixture /path/to/all-nodes.mcraft --upstream /path/to/pinned-source \
  --output /path/to/new-base-evidence
```

## Ordered function variable flow

`material_function_flow` checks variable types in native evaluation order using
an iterative abstract interpreter. It tracks definite assignments, potentially
undefined names, branch merges and type changes. Sequence and argument evaluation
preserve side effects. Both logical operands are evaluated, including the second
operand of `and` when the first is false. Known Boolean conditions select only
their actual branch; unknown conditions explore both. Immediate `isdefined`
guards, including their negation, refine variable presence without treating a
stored old predicate as a current fact.

Loop conditions run even with a zero iteration limit. The native condition is an
exit condition: true exits. Bounded loops retain their ordered assignments;
unbounded loops use a conservative abstract fixed point and retain an explicit
unbounded-loop flag. Type-flow success does not establish termination or numeric
domain safety.

Owned calls inherit the caller's environment after argument side effects, then
bind source defaults and arguments. Callee assignments remain local. Source
default types can shadow caller variable types without changing the caller.
The caller's scope propagates unchanged through nested functions. System-variable
availability follows actual control paths: a guarded `$pos` read can fall back
in Node scope and execute in Pixel Processor scope. Local names cannot enable
system variables outside their allowed scope.

Compilation and evaluation remain distinct. The prewalk checks every syntactically
reachable callee in both branches for operand contracts, cycles, the eight-level
limit and 4,096 expanded nodes. A never-selected callee with missing inputs still
refuses, matching native compilation. A valid but never-selected callee's variable
reads are not treated as executed reads. The existing operand inspector keeps its
strict default; only the flow checker explicitly defers scope availability to
control-path analysis.

Analysis allows at most 256 bodies, 4,096 variables, 100,000 node visits and two
million copied environment cells. A generator trampoline supports a 4,096-node
chain without Python recursion. These are bounds on admission analysis, not a
native execution or compute-cost estimate.

Qualification passes 127 checks across 29 native calls, including actual error
oracles for undefined reads, type drift, eager logical inputs and unavailable
callee scope. Native successes cover guarded assignments, loop state, default
shadowing across different types, argument effects and call-local type changes.
The 449-check intrinsic and 41-check widget-default regressions also pass.
Reports retain `numeric_values_qualified: false` and
`engine_admission_complete: false`. Concrete value evaluation, complete dynamic
base contexts, full native field prediction and whole-job budgets remain open.

```sh
python3 -B craft/tests/material_function_flow_check.py \
  --engine /path/to/dobe-material --fixture /path/to/atomic.mcraft \
  --output /path/to/new-flow-evidence
```

## Literal values and displayed colors

`material_values` predicts explicit native node values and exposed defaults from
admitted graphs and resolved references. It covers the 29 definitions, interface
bridge defaults/usages, Enum widgets, color widgets, bitmap resource names,
channel weights, curve/gradient arrays and local graph-instance overrides.
Processor bodies and parameter functions retain separate name inventories;
this comparison does not certify their bodies or effective cook-time clamps.
Missing empty native parameter maps are valid because the pinned serializer
omits them. Unexpected, missing, duplicate or malformed records fail comparison.
Boolean/numeric distinctions and the sign of zero survive semantic comparison.

Displayed RGB uses the pinned engine's binary32 sRGB transfer, with explicit
rounding at each operation and the fixed host `powf` ABI. No document can select
a library or symbol. The graph inspector rejects a finite source color if that
transfer overflows: a real private-engine counterexample serializes the resulting
nonfinite component as JSON `null`. Alpha is not gamma-converted. Gradient cells
are already linear and therefore do not receive the displayed-color transfer.
The ABI has native comparison evidence on this macOS ARM64 host; Linux and
clean-machine qualification remain open.

Array ordering follows the native total order for finite binary32 numbers,
including negative zero before positive zero. A source gradient with positive
zero followed by negative zero previously passed ordinary numeric ordering but
changed its first distinct stop on native import. Admission now refuses that
silent reorder. Already ordered signed-zero stops remain supported.

Qualification passes 177 checks across 40 native calls, including 28 color
samples, complete literal/default comparison, owned and nested image instances,
linear gradient cells, actual overflow/reorder counterexamples and malformed
native records. Existing graph, reference and base suites pass 71, 72 and 471
checks respectively. Original fixtures remain unchanged. This does not establish
arbitrary-color save/reopen fidelity, procedural numeric safety, complete native
field equality or whole-job admission. Reports retain
`engine_admission_complete: false`; Material remains outside the installed app
catalog until its durable runtime and full qualification are complete.

```sh
python3 -B craft/tests/material_values_check.py --engine /path/to/dobe-material \
  --fixtures /path/to/retained-native-evidence \
  --graph-fixtures /path/to/retained-graph-evidence \
  --reference-fixtures /path/to/retained-reference-evidence \
  --resource-fixture /path/to/png-bitmap.mcraft \
  --output /path/to/new-values-evidence
```

## Complete serialized state before cooking

`material_model` composes the admitted container, resources, graphs, references,
literal conversions and base records into the complete expected native package.
It retains all graph and package metadata, folder order/descriptions, exposed
editors/ranges/defaults, preview bindings, typed ports, instance interfaces,
connections, node positions, base functions, processor functions and patterns.
Frames, comments and pins are predicted at their actual ownership level: image
graph IDs follow image nodes, embedded annotation IDs start at one, and standalone
function annotations live on the document graph. No observed native fields are
removed to make comparison pass. Exact key inventories, list order, scalar types
and signed zero are checked iteratively.

The predicted interfaces represent the admitted source declarations. If native
inference produces a different image kind, comparison refuses the discrepancy
instead of adopting the changed interface. Resource payloads are not serialized
by the upstream native model, so their byte identity still requires the separate
resource and cold-member checks. Archived external references retain an explicit
handoff requirement; the engine's external-loading refusal remains unchanged.

The maintained private engine adds `snapshot <input>`. It opens the document
through the existing restricted loader and serializes editable state without
calling the headless inspection path, which cooks automatically. The command
checks that the cook cache is empty and the document still needs cooking, then
returns `nativePackage`, `loadWarnings`, `cookedNodeCount` and `pendingCook`.
It accepts exactly one input path and no flags. The runtime must first admit the
immutable input and apply process/resource limits; this command is not a sandbox
or a public arbitrary-path interface. A successful snapshot is not permission to
cook, and is not a successful customer generation job.

Qualification passes 215 checks across 76 actual native calls, plus 1,234 refused
field mutations. It covers all 29 node definitions, all 85 intrinsic schemas,
all four pattern kinds, six dynamic base fields, parameter functions, nested
calls, metadata, preview bindings and all annotation ownership levels. Five rich
fixtures pass exact canonical archive-member preservation through a cold save
and independently predicted native models after reopening. An undefined-variable
body snapshots with no cooked nodes but fails when ordinary `info` evaluates it.
Stale image-kind declarations and malformed snapshot arguments refuse. All
original source fixtures remain unchanged. The 46-check native regression passes.

Full runtime admission, dynamic evaluation contexts, aggregate compute bounds,
arbitrary-color cold fidelity, external handoff and durable customer operations
remain open. The complete serialized-state flag covers the editable model only;
`engine_admission_complete` remains false. Material is not yet installed or
registered in the product runtime.

```sh
python3 -B craft/tests/material_model_check.py --engine /path/to/dobe-material \
  --fixtures /path/to/retained-native-evidence \
  --graph-fixtures /path/to/retained-graph-evidence \
  --reference-fixtures /path/to/retained-reference-evidence \
  --procedural-fixtures /path/to/retained-procedural-evidence \
  --base-fixtures /path/to/retained-base-evidence \
  --resource-fixture /path/to/png-bitmap.mcraft \
  --output /path/to/new-model-evidence
```

## Lossless managed project preparation

`material_document.prepare` now prepares an owned project directory using the
complete source/model checks and the bounded private snapshot command. Existing
MCraft archives remain byte-identical. A bare SBS document becomes the unchanged
`source.sbs` member of a deterministic MCraft wrapper; its XML and embedded
resources are not rewritten. The original input is retained separately, alongside
stable source selectors, the independently predicted native model and an
inspection report. Source node IDs are strings so values beyond JavaScript's
exact integer range remain usable; native node indices are recorded separately.

This policy addresses a real precision defect in the native writer. For displayed
RGB `[0.4539059751422342, 0.41043622085578124, 0.7616346790648817]`, an unedited
native save changes the linear green channel from `0.14030027389526367` to
`0.14030025899410248`. Managed preparation preserves the original bytes and both
native snapshots retain the original value. It does not invoke native save.
Future managed revisions must preserve unrequested source fields and pass an
explicit requested-change comparison; passing data through the lossy writer is
not an acceptable revision shortcut. The upstream writer itself remains lossy.

Two fresh engine processes independently reopen the prepared file. Each must
match the complete expected root-package model, report no warnings, retain an
empty cook cache and leave its input bytes unchanged. The report identifies the
native package actually compared; source inventory may also contain unused
archived packages. Linked package execution remains refused pending its immutable
handoff. Native parsing uses the existing cancellable transport, a shared wall
and CPU deadline, bounded pipes and file size, and the worker's process group
when present. The outer durable worker still owns aggregate resource limits and
publication; this module is not an operating-system sandbox.

Snapshot JSON is bounded before allocation and rejects duplicate keys, invalid
Unicode, excessive nesting, nonfinite values and integer overflow. It admits the
full finite binary32 range required by Material, including values larger than
the numeric domain used by Animate's parser. Cancellation, expired deadlines,
changed native inputs and preparation errors remove the newly created private
output directory. Existing destinations and source symlinks refuse without
replacement. Original inputs remain unchanged.

Qualification passes 301 checks with 128 successful native calls out of 130
attempts; the two other attempts stop before launch on cancellation or an expired
deadline. It covers 28 color samples, embedded and archived image resources,
metadata, functions, graph instances, pattern canvases, repeated byte-identical
reimports, large source IDs and failure cleanup. The native writer counterexample
is retained separately. This qualifies managed import/preparation and cold
inspection, not rendering or the writer's general round-trip fidelity. The managed preparation contract now backs the four durable source operations
described below. Cooking, exports, preview, external handoff and installed
qualification remain required.

```sh
python3 -B craft/tests/material_document_check.py --engine /path/to/dobe-material \
  --fixtures /path/to/retained-native-evidence \
  --graph-fixtures /path/to/retained-graph-evidence \
  --reference-fixtures /path/to/retained-reference-evidence \
  --model-fixtures /path/to/retained-model-evidence \
  --resource-fixture /path/to/png-bitmap.mcraft \
  --output /path/to/new-document-evidence
```

## Precise typed scalar revisions

`material_revision` applies an atomic batch of 1–128 targeted edits against an
expected source SHA-256 and per-field expected values. Supported selectors cover
existing node parameters, graph base parameters, exposed or connectable input
defaults, graph attributes, graph dimensions, node positions, output labels,
procedural constants, pattern parameters and curve/gradient cells. Package and
graph identities are explicit. Node/cell IDs use canonical decimal strings.
Procedural bodies use their inspected source index within the hash-identified
revision; scalar replacements preserve the element inventory and those indices.

Values carry native source types such as `float4`, `int2`, `bool` or `text`.
Numeric input is explicitly converted to binary32 where the native format uses
it; Boolean coercion and silent type changes refuse. Graph dimensions use log2
Int2 values. Node positions use native top-left Float2 coordinates, accounting
for the SBS layout offset and refusing a result that cannot retain the requested
native value. Displayed node colors use their existing sRGB conversion; gradient
cells remain linear. Dropdown defaults also update their redundant current-value
field while preserving every choice label.

The bounded XML parser records source byte spans separately from the ordered
syntax tree. Revision replaces only selected scalar elements. Every unrequested
XML byte and every non-edited archive member stays exact, including resources,
unrelated procedural bodies and colors affected by the native writer defect.
ZIP metadata is regenerated when an archive changes; decoded members are the
preservation contract. UTF-8, BOMs, quote styles, explicit closing tags and `>`
inside quoted attributes retain correct offsets. No complete XML serialization
or native save can normalize unrelated fields.

All selectors and optimistic preconditions are resolved before changing bytes.
Duplicate/overlapping targets refuse. The complete proposed document is readmitted
before any native access, then the managed preparation path verifies full native
state through two fresh snapshots. Failed or cancelled preparation removes its
new staging input and output directory. Existing destinations and original
sources remain untouched. The revision report distinguishes requested values,
normalized source values, derived dropdown updates and verified native state.

Qualification passes 86 checks across 33 native calls. It covers all ten selector
kinds, every exposed scalar/vector type, dropdown synchronization, source IDs,
Unicode/lexical preservation, procedural and pattern constants, linear gradient
cells, resource preservation and an unrequested problematic color. Negative cases
cover stale hashes/values, duplicate targets, missing selectors, type coercion,
nonlinear color overflow, oversized dimensions and invalid XML characters.
Cancellation and destination preservation also pass. Container regression passes
108 checks with 1,000 mutations; managed-document regression passes 301 checks.

These selectors address existing scalar edits. Structured authoring and structural
changes use the separate source-tree interface described below. Durable source operations and bounded native evaluation are described below.
Durable map export and CPU preview are described below; installed qualification remains pending.
Successful revision verification does not grant execution admission or visual approval.

```sh
python3 -B craft/tests/material_revision_check.py --engine /path/to/dobe-material \
  --fixtures /path/to/retained-native-evidence \
  --graph-fixtures /path/to/retained-graph-evidence \
  --model-fixtures /path/to/retained-model-evidence \
  --base-fixtures /path/to/retained-base-evidence \
  --document-fixtures /path/to/retained-document-evidence \
  --resource-fixture /path/to/png-bitmap.mcraft \
  --output /path/to/new-revision-evidence
```


## Structured authoring and atomic structural revisions

`material_source.create` builds a portable archive from named SBS trees and owned
binary assets. Each tree element has exactly `tag`, `attributes` (string values)
and ordered `children`. This is a general source-authoring interface for the
admitted SBS schema, rather than a fixed list of recipes or arbitrary native
commands. XML names, namespaces, element counts, depth, attributes and encoded
bytes are bounded. Complete container, resource, graph, reference and native-model
admission follows serialization. Assets cannot masquerade as source documents.
The authoring report remains unverified until native preparation succeeds.

Managed preparation now retains `native/source-index.json`: the current portable
document SHA-256 and every source element's index, parent index, tag and exact
subtree SHA-256. The index refers to the stored document, including when an
imported bare SBS has been wrapped. Indices are revision-specific; a structural
change can renumber subsequent elements. Callers must inspect the new revision
before issuing another batch. `material_source.tree` exposes an admitted subtree
in the typed authoring form. Whitespace outside a requested replacement remains
unchanged; formatting inside that explicitly replaced subtree can change.

Structural batches contain 1–128 operations and require the original document
SHA-256. Element operations also require the package name, element index and
subtree digest:

- `replace` replaces that complete subtree with an explicit authored tree.
- `remove` removes that subtree.
- `insert` adds an authored child before a selected direct child, or appends when
  `before` is null. Multiple insertions at one location retain request order.
- `asset.add`, `asset.replace` and `asset.remove` change owned binary members.
  Replacement and removal require the existing member's SHA-256.

All selectors and digests bind to the original snapshot. Overlapping element
ranges, repeated asset targets, stale identities, invalid anchors, unsafe names
and unexpected fields refuse. Empty containers expand without reserializing the
surrounding document. A complete proposed revision is readmitted atomically, so
adding a node and wiring it, or adding a resource record and its bytes, can occur
in one coherent batch. Dangling references, duplicate IDs and orphan assets
refuse before native access. Aggregate payload and resulting XML budgets apply.

Every unrequested source byte and unchanged member stays exact. Updated archives
use deterministic stored ZIP entries; original ZIP metadata is not the contract.
A bare SBS revision stays bare when it needs no added members. Adding an owned
asset explicitly converts it to a lossless SBS wrapper. Preparation verifies the
report's data digest, retains authored bytes and evidence, and compares the full
native root model through two fresh non-cooking snapshots. It never invokes the
lossy native writer. Failed preparation removes only its own staging file and
new directory. Changes to the original during verification invalidate the attempt
without overwriting the concurrent change.

Qualification passes 109 checks across 34 actual native calls. An original typed
tree creates a two-map 32×32 material. Tests add absent metadata and graph seed,
insert/remove nodes and change wires, attach/replace/remove an owned bitmap, and
replace a procedural body with an original two-constant sum. Six native exports
match independently known complete pixel arrays for base color and unchanged
roughness; the procedural cook returns exactly 0.75. Every generated source
selector is checked against original byte spans and parent relationships. Stale
and conflicting edits, malformed trees, path escapes, orphan assets, cancellation,
existing-file preservation and concurrent-input mutation refuse. Existing managed
document and scalar-revision suites pass 301 and 86 checks respectively.

These small trusted render examples demonstrate real authored output. They do
not qualify unrestricted cooking, aggregate resource admission, external linked
packages, durable public operations or installed delivery. The durable source operations below preserve initial-source lineage across
revisions. The original production recipes are described below. Installed
qualification and Material-to-Texture handoff remain part of the complete
software goal.

```sh
python3 -B craft/tests/material_source_check.py --engine /path/to/dobe-material \
  --atomic /path/to/retained-atomic.mcraft \
  --output /path/to/new-source-evidence
```


## Durable source operations through the product CLI and MCP

The source runtime registers `material.create`, `material.import`,
`material.inspect` and `material.edit`. They use the same project/job/revision,
asset authorization, idempotency, cancellation, recovery and publication paths
as other applications. The maintained `dobe-material` binary must be on PATH;
its full pinned version is verified before snapshot execution. This changes the
source runtime only. The immutable dev.44 package still contains eleven apps
and no Material engine. Material capabilities now include the bounded cook and
map export and preview operations described below; installed qualification remains pending.

`material.create` takes `documents`, a mapping from archive SBS member names to
structured source trees, and optional `assets`, a mapping from owned binary member
names to imported asset IDs. `material.import` takes one `asset` ID for an admitted
SBS or MCraft document. Both require a new project. `material.inspect` takes empty
parameters and an explicit source revision. `material.edit` requires a source
revision, its current `native/document.mcraft` SHA-256, and exactly one of `edits`
(the ten scalar selector kinds) or `operations` (the six structural kinds).
Structural binary additions/replacements use `asset` IDs instead of raw bytes;
member preconditions still use SHA-256. Unknown commands, filesystem paths,
ambiguous edit lists and cross-project assets refuse.

```json
{
  "expected_sha256": "<current document SHA-256>",
  "edits": [{
    "kind": "node.parameter",
    "package": "package.sbs",
    "graph": "Original",
    "node": "3",
    "name": "outputcolor",
    "expected": {"t": "float4", "v": [1, 0, 0, 1]},
    "value": {"t": "float4", "v": [0, 0, 1, 1]}
  }]
}
```

Requests are bounded to 8 MiB; larger source documents use asset import. Binary
assets are materialized only in the disposable attempt. Every referenced resource
byte belongs to the resulting native archive, so portable revisions do not depend
on these transient paths or a customer's original filesystem. The same project
asset can be reused in successive revisions without colliding with old staging
files. Asset IDs are authorization references, not content hashes.

Every revision retains `native/original.input`, the initial exact imported or
authored bytes, plus `native/origin.json` with their format and SHA-256. The current
editable document, complete native model, object map and source selector index
remain separate. Initial bytes and their original operation recipe survive edits,
inspection, portable bundle export/reimport and further edits. Each inspection
report identifies the initial source and preceding document hashes. Lineage or
original-byte mismatch fails before native access; checksum validation also
rejects tampered portable bundles. This preserves provenance within the managed
project, without claiming external historical authenticity.

Source operations run fixed non-cooking snapshots; the separate cook operation
uses the bounded evaluation route described below. New files stay in a
disposable attempt until the supervisor checks its lease, deadline, cancellation
and project head before publishing the complete revision. Failed imports, stale
edits or concurrent-head conflicts publish no partial project revision. Previous
revisions remain immutable. The output manifest includes only current reports;
obsolete change reports and private input copies are not carried forward.

`material_runtime_check.py` passes 71 checks across fifteen real durable jobs:
twelve succeed and three deliberately fail for stale source, malformed source
and external dependency admission. It exercises submitting-client disconnection,
idempotency, the product MCP, source CLI, scalar and structural edits, owned bitmap
assets, repeated asset reuse, initial lineage, portable reimport/editing and scoped
refusals. `material_recovery_check.py` observes actual native snapshot children on
a 5,005-node input before cancellation and supervisor death. Both process groups
terminate without publication. Controlled local lease expiry records interruption;
no automatic replay occurs, and explicit retry succeeds. This is process recovery
evidence, not a machine reboot, clean-machine install or hosted-isolation proof.

```sh
python3 -B craft/tests/material_runtime_check.py --engine /path/to/dobe-material \
  --resource /path/to/png-bitmap.mcraft --external /path/to/linked-package.mcraft \
  --output /path/to/new-runtime-evidence
python3 -B craft/tests/material_recovery_check.py --engine /path/to/dobe-material \
  --output /path/to/new-recovery-evidence
```


## Bounded full-size graph cooking

`material.cook` takes an explicit source revision and `{"graph":"folder/name"}`.
It preserves the current editable source and initial-source lineage, then writes
`exports/cook.json` with resolved base values, parameters, typed output values,
raster dimensions/ranges and shared usage counters. The graph path refers to the
root package's admitted graph. A standalone function, missing graph or unresolved
external dependency refuses. This operation evaluates the graph. Use
`material.export` for map files and `material.preview` for the bounded CPU preview
contract below. Cooking alone does not qualify a rendered preview.

The maintained engine adds the private `evaluate <input> <graph-index>` route.
It loads an empty session through the restricted loader, never the automatic
preview cook used by old headless commands. It requires an unrecovered, uncooked
source, evaluates only the selected full-size graph and its instances, and never
saves the source. Native output still includes the complete package; the runtime
compares it with the admitted model before accepting the cook report. Source
bytes are checked again after execution. Extra paths, flags and invalid graph
indices refuse. Arbitrary native commands remain unavailable through the product.

The Dobe-only evaluation budget travels through recursive image instances. After
native dynamic base resolution and before raster work or error-image creation,
it charges each node visit and requested image output. Nodes with no declared
output ports still charge the implicit output used by the native engine. Cache
hits are charged conservatively. Limits per evaluation are 16,384 node visits,
16,777,216 texels per image and 67,108,864 aggregate requested output texels.
Values use no raster charge when their ports are explicitly typed as values.
These counters bound requested output work; they do not prove a bound for every
intermediate allocation. The durable supervisor continues to enforce aggregate
resident memory, attempt disk, process count, CPU and wall deadlines. The native
function evaluator also retains its 100,000-step per-evaluation limit.

Dynamic dimensions and inherited context use the actual pinned evaluator's
seed/size/format/pixel-size/pixel-ratio/tiling order. No independent interpreter
guesses a dynamic dimension before allocation. Tests prove that a later pixel-size
function sees newly resolved dimensions and a tiling function sees newly resolved
pixel ratio. An oversized dynamic raster and an oversized child instance both
refuse through the shared budget, even when their enclosing source graphs remain
valid editable documents.

Budgeted failures create no magenta recovery image and stop that graph. An error
inside a child graph propagates to its instance. Every produced image component,
scalar/vector result and evaluated scalar/vector parameter must be finite before
being accepted or cached. Native numeric, domain, budget or cancellation failures
exit unsuccessfully and become failed durable jobs with no revision publication.
The previous project head and initial editable source remain available. Legacy
private engine behavior is unchanged when the new budget is not selected; the
public adapter uses only the explicitly qualified routes.

The compute suite passes 45 checks across 50 instrumented native attempts and six
real durable jobs; worker subprocess calls are additional to that instrumented
count. Coverage includes original maps, all six dynamic base fields, context order,
recursive instances, exact procedural arithmetic, numeric overflow, per-image and
aggregate budget refusals, invalid route arguments, cancellation and preservation.
A successful durable cook publishes its evidence; overflow and budget jobs fail
without replacing the imported source revision. Separate recovery evidence observes
live `evaluate` children on a 5,005-node document before cancellation and supervisor
death. Both process groups terminate, original heads remain, and explicit retry
succeeds after controlled local lease expiry. The 71-check/fifteen-job source
runtime suite and 46-check/40-call legacy native suite also pass with this build.

Source build 8 retains the pinned upstream revision, uses twenty-five maintained
patched files and leaves Cargo.lock unchanged. The 26-file ARM64 native package
verifies against its lock/manifest, links only system libraries and declares
macOS 12.0. This is local native and source-runtime qualification, not installed
Material delivery, clean-machine compatibility, reboot or hosted isolation.

```sh
python3 -B craft/tests/material_compute_check.py --engine /path/to/dobe-material \
  --fixtures /path/to/retained-native-evidence \
  --base-fixtures /path/to/retained-base-evidence \
  --output /path/to/new-compute-evidence
python3 -B craft/tests/material_recovery_check.py --engine /path/to/dobe-material \
  --operation cook --output /path/to/new-cook-recovery-evidence
```

## Export encoding interoperability

The native seven-format encoder exposes PNG, JPEG, TGA, BMP, WebP, OpenEXR and
Radiance HDR. PNG supports 8-bit and 16-bit samples. The float formats discard
alpha; HDR uses shared-exponent RGBE rather than IEEE float samples. Native
color-space defaults can encode color through sRGB even for EXR. The durable export contract below selects these policies explicitly and refuses
silent alpha loss; integer/RGBE quantization remains explicit. TIFF is not an export format at this pin.

An actual native export probe found two interoperability gaps. The upstream TGA
RLE writer emits packets across scanlines that Pillow refuses. The Dobe feature
now emits uncompressed TGA through the existing native encoder, preserving the
samples while allowing complete independent decoding. Upstream non-Dobe behavior
is unchanged. Native EXR output uses 64×64 single-level tiles and RLE compression;
the shared bounded EXR reader now admits that layout as well as qualified
uncompressed, ZIPS and ZIP tiles. It checks the complete directory, coordinates,
levels, payload coverage, size-limited decompression and every finite sample.
Source bytes remain exact. Deep, multipart and multilevel EXR remain refused.

Local export encoding evidence has 171 checks, eight format/depth combinations,
16 actual map files and 32 complete native resource roundtrips. Sixteen independently
written RGB/RGBA EXR images exercise spatially varying pixels, half/float samples, all
four admitted compression modes, edge tiles and reversed physical storage. Every
roundtrip preserves the embedded bytes and editable source, performs a bounded
finite bitmap cook, and compares every decoded output pixel with an independent
oracle. The native 128×128 export also exercises multiple 64×64 tiles. The shared
image suite covers 293 cases plus supplied native images.

These small, owned fixtures use the legacy private export route solely to
qualify encoding and decoding. They do not authorize that route for public jobs.
The durable export operation described below uses the bounded evaluator, explicit
format/depth/color/alpha policies, exact inventories and source-preserving publication.

```sh
python3 -B craft/tests/material_export_codecs_check.py \
  --engine /path/to/dobe-material --output /path/to/new-codec-evidence
```

## Durable map export

`material.export` now runs through the same durable product CLI and MCP as source
creation and revision. It requires a source revision and these parameters:

```json
{
  "graph": "Original",
  "format": "png",
  "depth": 16,
  "outputs": ["basecolor", "roughness"],
  "color_spaces": {"basecolor": "srgb", "roughness": "raw"},
  "discard_alpha": false
}
```

`graph`, `format` and `depth` are required. Omit `outputs` to export every raster
output bridge; the report identifies non-raster outputs skipped in that case.
An explicit selection must contain unique existing raster identifiers. A selected
non-raster output fails the job. A color-space override must name a selected
raster. Unknown options fail rather than reaching an arbitrary native command.

Supported combinations are PNG at 8 or 16 bits, JPEG (`jpg`), TGA, BMP and WebP
at 8 bits, and EXR/HDR with `depth: 32`. EXR contains RGB IEEE float32 samples;
HDR uses RGBE shared-exponent quantization. Integer formats clamp to [0,1] before
quantization, and JPEG is lossy. These policies appear in each map record.
The original editable float source remains unchanged by export.

Color maps use the native usage-specific sRGB transfer by default for integer
formats. EXR and HDR default to linear color. Grayscale maps default to raw data.
`srgb`, `linear` and `raw` are explicit overrides; an sRGB override on a grayscale
map refuses because the native encoder would ignore it. Transfer-generated
nonfinite values refuse. RGBE refuses negative samples and pixel maxima whose
native exponent conversion would overflow or underflow its nonzero range.
This prevents silent exponent wrapping. JPEG, EXR and HDR refuse nonopaque alpha
unless `discard_alpha: true`; the report identifies maps that discarded it.

The private `maps` route performs one full-size cook using the same shared native
budgets and error propagation as `material.cook`. It exports the resulting raster
objects directly, without another cook, preview resolution, native save or
recovery images. Limits are 256 maps, 33,554,432 exported texels, 64 MiB per encoded
file and 512 MiB in total. Evaluation has its own node/aggregate raster limits;
the worker still enforces process, RSS, disk, CPU, wall, lease and cancellation
limits. These counters do not prove every temporary native allocation is bounded.

Files use fixed native node IDs, for example `exports/maps/map-4.png`. Graph and
output names remain metadata and cannot become paths. `exports/maps.json` records
identifiers, usage, selected transfer, actual dimensions, encoding, source
channels, alpha policy, byte sizes, SHA-256 hashes, full-decoder results and cook
usage. The runtime independently compares the complete native model and output
inventory, decodes every file, checks actual PNG depth/EXR channel sample types,
checks the exact directory inventory, and verifies the editable source bytes.
Only completed output sets enter the durable revision. Initial source and origin
recipe remain portable and immutable across exports and subsequent edits.

The operation is registered in the source runtime and requires the maintained
engine with the `maps` route on PATH. Installed dev.44 remains unchanged. Managed Texture/material handoff is described below; installed Material
qualification remains a separate requirement.

```sh
python3 -B craft/tests/material_maps_check.py --engine /path/to/dobe-material \
  --output /path/to/new-map-evidence
python3 -B craft/tests/material_recovery_check.py --engine /path/to/dobe-material \
  --operation export --output /path/to/new-map-recovery-evidence
```

Durable map qualification passes 204 checks across fourteen public jobs (thirteen
successful and one deliberate missing-output failure). It covers all eight
format/depth combinations, disconnected MCP clients, a CLI submission, idempotency,
exact inventories, independent full-image/float-sample expectations, a 512×256
full-size export, cold byte-repeatability, portable editing, unchanged roughness
and immutable initial sources. It also covers explicit alpha loss, raw/linear
color policies, negative and extreme RGBE values, transfer overflow, native raster,
map-count and encoded-byte budgets, source traversal refusal, Unicode metadata,
existing destination preservation and cleanup after a truncated native output.

Two actual live native `maps` children are cancelled or interrupted under the
supervisor. Both process groups disappear and prior project heads remain intact.
Controlled lease expiry marks the interrupted job without automatic replay;
explicit retry succeeds on attempt two. This proves local process recovery, not
machine reboot, clean-machine installation or hosted isolation. The unchanged
source/lineage suite passes 71 checks across fifteen jobs; bounded evaluation
regression passes 45 checks across six jobs and the native baseline passes 46
checks across forty calls.


## Durable CPU preview

`material.preview` renders an existing source revision through the product CLI
and MCP. It performs one full-size bounded cook and uses those same raster objects
for the preview. It never opens an editor, changes saved preview state, invokes an
automatic preview-resolution cook or saves the editable source through the native
writer. Initial source bytes and the origin recipe remain immutable and portable.

A 2D request names exactly one output and its explicit display dimensions:

```json
{"graph":"Original","view":"2d","width":512,"height":256,"output":"basecolor"}
```

The output must be a raster. Resizing uses the native filtered image operation;
explicit dimensions can change aspect ratio. Grayscale uses raw display values,
color uses the sRGB transfer, and alpha is retained in the RGBA8 PNG. This is a
display preview; use `material.export` for map format, depth and transfer policies.

A 3D request selects a built-in mesh and lighting environment:

```json
{
  "graph":"Original","view":"3d","width":512,"height":512,
  "scene":"sphere","environment":"studio","supersample":2,
  "ao_rays":8,"key_light":1,
  "channels":{"baseColor":"basecolor","roughness":"roughness"}
}
```

`graph`, `view`, `width` and `height` are required. The 3D defaults are sphere,
studio, yaw 35 degrees, pitch 25 degrees, distance 3.2, target [0,0,0], tiling 1,
exposure 0, environment rotation 0, supersample 2, AO rays 0, key light 0,
transparency enabled, displacement 0, displacement level 0 and 500,000 triangles.
Normal-Y flip, visible environment and alpha view default to false. All effective
settings are recorded after explicit binary32 conversion.

Meshes are `material_ball`, `sphere`, `cube`, `rounded_cube`, `cylinder`, `torus`,
`plane`, `crate` and `udim_plane`. Environments are `studio`, `contrast`, `overcast`,
`sunset`, `warehouse` and `night`. Unknown identifiers refuse instead of silently
falling back. Channels are `baseColor`, `normal`, `roughness`, `metallic`, `height`,
`ambientOcclusion`, `emissive` and `opacity`. Default selection uses output usage,
including the native `diffuse` alias for `baseColor`. Duplicate usage requires an
explicit channel-to-output mapping. Every selected channel must be a raster.

Each dimension is 1–4,096, with at most 16,777,216 pixels and 64 MiB of encoded PNG.
Supersampling is 1–4 per axis, with at most 67,108,864 samples. AO rays are 0–32.
A conservative work count multiplies samples by eight transparent surfaces and
one primary ray plus AO rays and an optional key-light ray. It cannot exceed
1,073,741,824. This is a work bound, not a measured ray count or compute-price claim.
The worker's process, RSS, CPU, disk, wall, lease and cancellation limits still
apply. No claim covers every temporary native allocation.

Finite setting ranges are yaw and environment rotation −360 to 360 degrees,
pitch −89 to 89 degrees, distance 1.05–50, each target coordinate −10 to 10,
tiling 0.1–64, exposure −16 to 16, key light 0–16, displacement 0–0.5 and
displacement level 0–1. The triangle budget is 64–2,000,000; both the base mesh
and resulting displaced geometry must fit it. Displacement requires a height
channel. Height samples are bounded before interpolation and seam accumulation,
even when a tiny displacement would otherwise conceal intermediate overflow.
Scaled displacement cannot exceed eight scene radii. Normal-map encoded XYZ
samples must lie in [0,1]. Unused alpha does not participate in normal or height
range checks. Geometry and final linear/display samples must be finite.

The 3D PNG has an opaque background. `transparency` controls material opacity
composited against that background; it does not request a transparent canvas.
`alpha_view` displays material alpha as grayscale. A normal or height override
changes how the selected raster is interpreted, without altering its source.

The revision contains `exports/preview/preview.png` and `exports/preview.json`.
The runtime compares the full native model, bounded evaluation report, effective
settings, selected output identities/dimensions, geometry and work budgets. It
then decodes the entire RGBA8 PNG, checks the exact directory inventory, byte size
and hash, and confirms unchanged editable source bytes. Failed previews publish
no revision. `render_qualified` and `preview_performed` describe this supported
route; `visual_approval` remains false.

Local qualification passes 161 checks across six durable jobs, with five successes
and one deliberate missing-height failure. All nine meshes show the material;
six environments produce distinct images. Independent pixel expectations cover
2D color, grayscale and alpha, the entire transparent 3D backdrop, and alpha view.
Evidence also covers cold byte-repeatability, explicit channel selection,
displacement, AO/key-light/sample controls, malformed settings, work limits,
nonfinite shading, intermediate displacement overflow, unused alpha, truncated
native output, CLI/MCP execution, portable editing and source lineage. These small
fixtures establish behavior, not general production quality or visual approval.

Recovery evidence observes two live native `preview` children: cancellation and
worker interruption both remove the registered process group and preserve the
prior project head. Controlled lease expiry does not replay work automatically;
explicit retry succeeds on attempt two. That evidence used build 12; build 14
adds height working-range and unused-alpha validation, with the same process
route. It does not establish reboot, installed or hosted recovery.

```sh
python3 -B craft/tests/material_preview_check.py --engine /path/to/dobe-material \
  --output /path/to/new-preview-evidence
python3 -B craft/tests/material_recovery_check.py --engine /path/to/dobe-material \
  --operation preview --output /path/to/new-preview-recovery-evidence
```

Material now has eight source-runtime operations. Installed dev.44 still contains
eleven applications and excludes Material. Additional production recipes and
immutable archived dependency handoffs, installed packaging and the complete seventeen-app
Local/Cloud release requirements remain open.


## Original reusable material recipes

`material.create` accepts a versioned recipe request as an alternative to authored
`documents`. The recipes compile into ordinary editable SBS graphs, with no
converted upstream function bodies or image resources. Each project owns its own
source and rendered outputs. Only the graph-building recipe is reused.

```json
{
  "recipe":"ceramic_tiles",
  "version":1,
  "resolution":256,
  "controls":{"repeat":8,"grout":0.08,"bevel":0.08,"color_r":0.18,
              "color_g":0.32,"color_b":0.4,"roughness":0.28,"relief":0.12}
}
```

The first catalog contains `ceramic_tiles` and `ribbed_metal`. Ceramic tiles have
square faces, recessed grout and smoothstep bevels. Ribbed metal has periodic
rounded ribs. Both produce `baseColor`, `roughness`, `metallic`, `height`, `normal`
and `ambientOcclusion` from a graph named `Surface`. Color, roughness and occlusion
follow the same surface pattern. OpenGL normals derive from the height map.
The metal recipe has metallic value 1; ceramic has value 0.

All color controls are linear-light scalar components. Common controls are
`color_r`, `color_g`, `color_b` (0–1), `roughness` (0.02–1), `relief` (0–1), and
integral `repeat`. Ceramic repeats 1–64 times per axis, with `grout` 0.01–0.3
and `bevel` 0.01–0.25. Metal repeats 1–128 times horizontally. Integral repeats
preserve seamless periodicity. `resolution` is a power of two from 32 to 1,024,
with default 256. Creation requires at least four pixels per repeat, so small
resolutions may require a lower repeat setting. Finite binary32 controls and version 1 are explicit; unknown
versions, controls and mixed recipe/document/asset requests refuse.

The product MCP capability response includes `production_recipes`, with IDs,
versions, descriptions, defaults, ranges, integral constraints and outputs.
The existing CLI `submit ... material.create --parameters <json>` accepts the same
request. Recipe creation still requires a new project. It authors and cold-opens
the graph; use `material.export` or `material.preview` to render it.

Every control becomes a named exposed graph input. Use `material.edit` with
`kind: "input.default"`, graph `Surface`, the control name, expected typed value
and current document SHA-256 for a precise revision. Other scalar and structural
editing routes remain available. Edits do not regenerate the graph or rerun the
recipe. A color-only revision therefore preserves height, normals, roughness,
metallic and occlusion. Later direct edits follow normal source admission; the
initial recipe ranges are not a permanent restriction on the editable document.

`recipes/material-production.json` records the original normalized controls,
recipe version, generated graph specification hash and original source hash.
It survives later revisions and portable project reopening unchanged. It records
creation provenance, not a claim that later edits still match the initial recipe.
`native/original.input` and the origin operation recipe remain immutable too.

The implementation avoids repeatedly asking an agent to design and serialize
these graphs. Native evaluation still runs for each export or preview. No rendered
image cache, cross-project pixel reuse, measured agent-token savings, production
compute price or general photorealism claim is implied. These are editable
procedural starting materials; visual approval remains separate.

```sh
python3 -B craft/tests/material_recipes_check.py --engine /path/to/dobe-material \
  --output /path/to/new-recipe-evidence
```


Recipe qualification passes 161 checks across six successful durable jobs. Both
recipes pass independent all-pixel expectations for all six maps at 128, 256 and
1,024 pixels per axis. The normal oracle differentiates the analytic height field
with wrapped boundaries. Cold exports are byte-identical in decoded pixels.
Actual displaced previews use all six channels. Portable recoloring changes only
base color and retains the other five maps, exact original source and original
recipe record. Both public CLI and MCP routes are exercised, including client
exit, idempotency and subsequent preview. Invalid versions, mixed requests,
nonfinite controls, nonintegral repeat and undersampled patterns refuse.

On this macOS ARM64 development machine, one measured six-map PNG8 export at
256×256 takes 0.296 seconds for ceramic and 0.154 seconds for metal. At 1,024×1,024,
the corresponding observations are 2.638 and 0.340 seconds. These wall-clock
observations include source admission, native snapshot, bounded cooking, encoding
and complete output decoding. They exclude queueing and agent reasoning, and are
not repeated statistical benchmarks, provider prices or billable CPU seconds.
Evidence is retained in `material-recipes-check-2/evidence.json` in the local
qualification workspace. The maintained native engine is unchanged.

A separate four-case boundary check proves that normalized recipe controls can
be reused exactly at both range endpoints. Admission accepts the binary32
representation of each endpoint, including values such as 0.02 whose exact
binary32 value falls slightly below the written decimal bound.


## Managed portable materials and Texture handoff

`material.bundle` exports an existing revision using `{ "graph": "Surface" }`
and optional `outputs`, a list of output identifiers. The default selects all
outputs with a material usage. Duplicate usages require an explicit selection;
`any`, missing outputs and selected non-raster outputs refuse. Every selected map
must have the same dimensions. The operation performs one bounded full-size cook
and produces `exports/material.mcmat` plus `exports/material.json` evidence.

The portable archive uses the standard `craft-material` version-2 manifest with
`source.mcraft`, `material.json` and `maps/map-<node-id>.png`. Source bytes are copied
exactly, including embedded image resources. No native save or legacy portable
export command rewrites them. Maps use PNG16; color maps use the recorded sRGB
transfer and data maps use linear/raw samples. Integer maps clamp to [0,1] and
quantize to sixteen bits; original floating-point source remains editable.
Exposed portable controls retain their complete metadata and effective values.
Image input declarations and presets are recorded, with source graph identity.
Nonportable control types remain in the exact source even when excluded from the
portable control list.

The admitted profile has a 1 MiB manifest, a 64 MiB source archive, 64 MiB per map,
256 MiB total archive/expanded bytes and 33,554,432 decoded map texels. The reader
checks complete ZIP headers, intervals, checksums and inventories, strict JSON,
source admission, exact manifest/source metadata agreement, output identity,
unique usage, transfer, dimensions and complete PNG16 decoding. Unknown members
or schema fields refuse. Existing outputs are preserved. A failed write removes
only its own partial output. The deterministic writer is byte-repeatable.

To reopen a bundle as an editable Material project, import its project-scoped
asset with `material.import` parameters `{ "asset": "<id>", "format": "mcmat" }`.
The runtime verifies every map against a fresh bounded cook of the contained
source before publishing the import. `native/original.input` retains the complete
original bundle, while `native/document.mcraft` retains the exact inner source.
Subsequent edits and bundle exports preserve that initial bundle. Without an
explicit format, `material.import` continues to admit SBS/MCraft sources.

`texture.material` applies a bundle asset to an existing Texture revision:

```json
{
  "asset":"<project-owned bundle asset>",
  "expected_sha256":"<current native/document.tcraft SHA-256>",
  "texture_set":0,
  "height_mode":"unsigned"
}
```

The default creates a linked fill at the top of the selected texture-set stack.
Optional `name` sets the new layer name. Supplying `layer` replaces the sources
and linked-material metadata of an existing linked fill in that texture set.
Replacement requires the same channel set and preserves the name, projection,
blend settings, masks, effects, stack position, other layers and allocator.
Every old resource remains intact. New maps and the exact Material source use
content-addressed resource names; identical owned bytes can be reused within the
project. This is not cross-project reuse of private generated imagery.

The handoff is an explicit runtime conversion from admitted version-2 manifests
to a fully predicted native Texture document. The pinned native Texture reader
accepts only version 1; that legacy reader is not invoked, patched to accept
unknown versions or fed a silently downgraded manifest. The actual native Texture
engine saves and cold-opens the predicted document, decodes all embedded maps,
and renders its output. Independent comparisons require every unrequested field
and old resource byte to remain exact. Only the new link's binary32 numeric
serialization can round within the same binary32 value.

Both maintained engines are required on PATH. The Material engine first recooks
the owned source and compares every encoded map byte, so a valid archive containing
stale or substituted maps cannot become a successful handoff. Ambient CLI lookup
from native projects, editor launching, linked automatic recooking and shared-home
library publication remain disabled. The whole operation uses one durable job.

Texture supports only its declared channel usages; unsupported usages or aliases
that target the same channel refuse. Color maps must have sRGB encoding, and data
maps must be linear. Normals use the portable format's OpenGL convention. Texture
resamples maps to the selected texture-set resolution. The report records source
map dimensions and target resolution; the link's scalar size field retains only
width, while exact dimensions remain in the original source and bundle.

If a Height map exists, `height_mode` is required. `signed` treats its encoded
[0,1] range as Texture's [-1,1] range. `unsigned` preserves the material's [0,1]
height values by encoding `(height + 1) / 2` for Texture's signed image sampler;
this conversion requires a grayscale PNG16 map and has at most 1/65535 additional
value error. Texture's exported integer height map encodes signed values back to
[0,1]. Existing normal/height compositing settings remain unchanged, so its final
normal map can combine the imported normals with the height contribution. The
raw embedded normal map remains exact. Supplying a height mode without a Height
map refuses.

Texture's link shows a subset of exposed-control presentation fields. Descriptions,
editor/clamp/step metadata and any other projected fields remain in the exact
source and retained bundle, and the report lists the projection explicitly.
The complete bundle is retained as `assets/material-<sha256>.mcmat`. Imported
asset IDs are used only in private attempt staging, so repeated application and
portable reopening do not depend on a prior project's asset IDs.

Local handoff qualification passes 133 checks across twelve durable jobs: ten
successes and two deliberate stale-source/substituted-map failures. It covers
public CLI/MCP, disconnected clients, idempotency, exact source roundtrip,
manifest and archive failures, independent Texture pixels, precise replacement,
owned resource reuse, cross-project asset denial and portable reopening. Sixteen
additional checks cover output subsets, absent Height, signed Height, embedded
bitmap sources, resampling, unknown outputs, existing-file preservation and failed
sync cleanup. The first run exposed a real retained-asset staging collision;
private staging and a separately retained content-addressed bundle fix it.
The initial edge fixture correctly failed ownership admission; its input is now
copied into the test's owned root. Neither refusal was weakened.

Four actual native children are observed during handoff cancellation/interruption:
two in the Material verification phase and two in the Texture phase. All registered
process groups disappear and prior project heads remain unchanged. Controlled
lease expiry does not replay interrupted work; explicit retries succeed on attempt
two. This is local process recovery, not reboot or hosted-isolation qualification.
Material source regression passes 71 checks across fifteen jobs; Texture authoring
regression passes 52 checks across four jobs. Both native binaries are unchanged.
Installed dev.44 does not include these new runtime routes or Material.

```sh
python3 -B craft/tests/material_handoff_check.py --material /path/to/dobe-material \
  --texture /path/to/dobe-texture --output /path/to/new-handoff-evidence
python3 -B craft/tests/texture_recovery_check.py --engine /path/to/dobe-texture \
  --material /path/to/dobe-material --bundle /path/to/material.mcmat \
  --phase material --source /path/to/baseline.tcraft --output /path/to/new-recovery
```

Repeat recovery qualification with `--phase texture` to observe the other native
engine. Installed Material packaging/recovery,
remaining native applications, billing and full Local/Cloud release requirements
remain open. No external native-reader interoperability or production readiness
is claimed for this admitted profile.


## Immutable archived package dependencies

The source runtime now prepares, inspects, edits, cooks, exports, previews and
bundles material graphs that reference other SBS members in the same owned
`.mcraft` archive. No new request shape is necessary. `material.create` can author
multiple `documents`; `material.import` consumes a project-scoped archive asset.
The CLI capability response reports `archived_dependencies_available`.
This completes the archived dependency execution prerequisite described as open
in earlier evidence sections. It does not enable ambient libraries, external
filesystem dependencies, cross-package bitmap reference syntax or remote access.

Admission resolves every declared package within the immutable archive. Existing
limits remain: 64 packages, aggregate resource/decoded-image limits, eight image
and function call levels, 4,096 expanded function nodes and 16,384 expanded image
nodes. Missing packages, escaping paths, library URLs, cycles, mismatched ports
and unaccounted members refuse before native execution. The runtime keeps the
original archive and each SBS byte sequence. A precise child-package edit changes
only the requested source span; unchanged root and sibling members stay exact.

The maintained native archive reader loads the bounded package inventory,
including declared but unused packages. It maps references to
`mcraft://dobe-archive!/<member>` only in memory. Managed snapshot, cook, map and
preview processes open without a disk-path package alias. Their registry therefore
cannot depend on the temporary attempt directory or a previous process. The
native automatic external loader and resource filesystem callbacks stay disabled.
Legacy private editor/session commands retain their existing document bookkeeping;
the product does not expose those commands as customer operations.

Before execution, an independent Python model predicts every package, every
instance identity and every serialized field. The native snapshot adds
`archivedPackages` for archives containing multiple packages. The runtime compares
the exact registry inventory, its root snapshot and every dependency, including
unused packages. Native evaluation reports the same inventory, which is compared
again after cooking. Missing, additional or changed packages refuse. Native
resource lookup uses the dependency's namespace; a caller's same-named bitmap
cannot replace the child's pixels. Shared raster counters and existing worker
limits cover nested image instances. Source paths never grant file access.

`exports/inspection.json` records `native_packages_compared`,
`immutable_archive_dependencies` and `archive_package_sha256`. The exact archive,
original source lineage, package selectors and editable graph objects remain in
the portable revision. `material.bundle` retains the entire dependency archive as
`source.mcraft`; its importer still verifies every map against a fresh bounded
cook. No native source reserialization or dependency flattening is used.

The dedicated local check covers image dependencies, relative nested dependencies,
eight archived function levels with independent arithmetic, unused packages,
namespace-colliding bitmap names, every exported pixel, relocated snapshots,
registry mutations, explicit nested raster-budget refusal, portable bundle recook,
child-only color revision and portable project reopening. It also submits through
the public CLI/MCP, exits those clients before execution and checks idempotency.

```sh
python3 -I -B craft/tests/material_dependencies_check.py \
  --engine /path/to/dobe-material \
  --references /path/to/material-references-check \
  --output /new/owned/dependency-check
python3 -I -B craft/tests/material_recovery_check.py \
  --engine /path/to/dobe-material --operation export --archived \
  --output /new/owned/dependency-recovery
```

Recovery observes real native map processes for an archived dependency, cancels
or kills the supervisor, proves process-group absence and prior-head preservation,
then proves controlled lease recovery without automatic replay and an explicit
successful retry. This is local process recovery, not machine reboot or hosted
isolation qualification. Installed dev.44 remains unchanged at eleven of seventeen
apps. Material packaging, remaining applications, Linux/Cloud, billing and the
explicit signing, clean-machine, reboot and provider release gates remain open.


## Installed development package: dev.45

The CLI-only `0.1.0-dev.45` package adds the maintained Material engine and the
current durable runtime. All eight Material operations run through the same
installed CLI/MCP with only `/usr/bin:/bin` supplied by the caller. Launchd owns
the isolated supervisor; submitting MCP clients exit before native work finishes.
The package supplies Python, image decoding and all native executables.

Installed evidence covers original recipe creation, inspection, bounded cooking,
six-map export, precise CLI color revision preserving five maps, CPU preview,
portable bundle export/import and immutable archived dependencies. The same
package qualifies `texture.material` with a three-package Material source,
retaining that exact editable source and the original Texture project.

The acceptance script runs nineteen durable jobs: seventeen success, one actual
native-preview cancellation and one supervisor-crash interruption. It proves
process-group absence, unchanged prior heads, no failed revision publication,
explicit attempt reconciliation and resumed editing. A queued Material request
survives rollback to dev.44 and finishes after reinstalling dev.45. The isolated
service is removed afterward. See `craft/tests/material_package_check.py` and the
local packaging instructions (`craft/local/README.md`).

The development archive has 2,311 entries, checked against every package byte,
mode and symlink target. Eleven prior engine packs remain unchanged. Earlier
statements that Material is absent from dev.44 remain historical evidence for
that immutable candidate; dev.45 is the current locally qualified package.
This is not general installed-release qualification: the conservative capability
flag remains false while clean-machine/reboot and release gates are open.
The complete seventeen-application Local/Cloud objective remains unfinished.
