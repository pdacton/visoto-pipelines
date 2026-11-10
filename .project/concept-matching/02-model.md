# Model

## Overview

```
dcat:Dataset ◀─ dcat:Distribution ─dct:conformsTo─▶ ap:DataStructure ▸ ap:Container ▸ ap:Slot
                                                                                          │
                     ┌──────────────── ap:valueDomain ───────────────────────────────────┤
                     ▼                                                                    │
            mdr:ValueDomain ◀─ mdr:valueDomain ─ mdr:DataElement ◀──── ap:dataElement ────┤
                                                      │ mdr:dataElementConcept            │
                                                      ▼                                   │
                                           mdr:DataElementConcept ◀ ap:dataElementConcept ┘
                                             │ mdr:objectClass   │ mdr:property
                                             ▼                   ▼
                                        mdr:ObjectClass     mdr:Property
```

Two datasets are comparable where their slots reach the same entry.

## Registry entries

| Entry | Made by | From |
|---|---|---|
| Value domain, code list | wrapper around a LINDAS code list: one for the list, one per version | LINDAS |
| Value domain, identifier | one per ID validator (AHV number, UID, EGID, …) | hand-written rule |
| Value domain, described | rule: datatype + unit + format; geometry type + coordinate reference system | the slot's profile |
| Object class, property | LLM, after looking up existing entries | the slot's name, context and values |
| Data element concept | rule: the pair of an object class and a property (ISO/IEC 11179) | the two parts found for a slot |
| Data element | rule: the pair of a slot's concept and value domain | the two links of a slot |

### Code lists

```turtle
<https://register.ld.admin.ch/mds/valuedomain/DV_KT_BEZ_GDE_SNAP> a mdr:ValueDomain ;
    dcterms:identifier "DV_KT_BEZ_GDE_SNAP" ;
    mdr:permissibleValues <https://register.ld.admin.ch/i14y/concept/DV_KT_BEZ_GDE_SNAP> ;
    sh:nodeKind sh:IRI .

<https://register.ld.admin.ch/mds/valuedomain/DV_KT_BEZ_GDE_SNAP/2024.1.0> a mdr:ValueDomain ;
    dcterms:isVersionOf <https://register.ld.admin.ch/mds/valuedomain/DV_KT_BEZ_GDE_SNAP> ;
    dcat:version "2024.1.0" ;
    mdr:permissibleValues <https://register.ld.admin.ch/i14y/concept/DV_KT_BEZ_GDE_SNAP/version/2024.1.0> ;
    sh:nodeKind sh:IRI .
```

- A slot links to a version when its values tell the versions apart,
  otherwise to the list.
- Hierarchical lists (canton, district, municipality in one list) are matched
  per xkos level; the link records the level (`ap:level`).
- Only the wrappers (about 340 lists and 728 versions) are in visoto-qlever.

### Described value domains

Made by rule from the slot's profile, so two slots with the same
representation get the same entry without any lookup. The IRI is built from
the properties, for example `…/mds/valuedomain/described/date-iso`,
`…/described/decimal-CHF`, `…/described/geo-MultiPolygon-EPSG2056`.

### Concepts

Created entries get an opaque identifier (labels change, IRIs must not), the
status "candidate" (`adms:status`), and provenance: the run and the slot they
were first created for (`prov:wasGeneratedBy`, `prov:wasDerivedFrom`).

```turtle
<https://register.ld.admin.ch/mds/dataelementconcept/c-3f9a1c20> a mdr:DataElementConcept ;
    dcterms:title "Municipality of residence of a person"@en ;
    mdr:objectClass <https://register.ld.admin.ch/mds/objectclass/c-77b0e1d4> ;   # Person
    mdr:property    <https://register.ld.admin.ch/mds/property/c-0a52c9e8> ;      # municipality of residence
    adms:status status:UnderDevelopment ;
    prov:wasDerivedFrom <slot> ; prov:wasGeneratedBy <run> .
```

Following ISO/IEC 11179, a data element concept is one object class plus one
property, and nothing else. Only object classes and properties are looked up
and created; the concept's identifier is derived from its two parts, and a
data element's from its concept and value domain, so neither needs a lookup.

The object class is the kind of thing the record describes, not the kind of
thing a value refers to. A column `Wohngemeinde` in a table of persons gives
the object class Person and the property "municipality of residence"; the
municipality itself appears in the value domain (municipality codes). So the
slots of one container normally share their object class, which is also the
container's `ap:mainObjectClass`.

Concepts are specific: "municipality of residence" and "municipality of work"
are two properties and so two concepts. Slots can still be compared more
coarsely through what they share:

| Shared | Meaning |
|---|---|
| Data element | same meaning, same representation |
| Data element concept | same meaning |
| Object class | about the same kind of thing |
| Property | the same characteristic, of different kinds of thing |
| Value domain | same representation |

## Links

```turtle
# proposal, regenerated on every run
<slot> ap:candidate [ a ap:Candidate ;
    ap:concept <…/mds/valuedomain/DV_KT_BEZ_GDE_SNAP/2024.1.0> ;
    ap:candidateRank 1 ; ap:candidateScore 0.97 ;
    ap:evidence [ ap:method "code-overlap" ; ap:containment 1.0 ; ap:coverage 0.27 ;
                  ap:level <…/level_2> ] ;
    prov:wasGeneratedBy <run> ] .

# accepted link: by a person (confirmations graph) or automatically by the run
<slot> ap:match [ a ap:Match ;
    ap:concept <…/mds/valuedomain/DV_KT_BEZ_GDE_SNAP/2024.1.0> ;
    ap:matchType skos:exactMatch ; ap:candidateScore 0.97 ;
    prov:wasAttributedTo <person-or-run> ] .

# shortcut, derived from every match
<slot> ap:valueDomain <…/mds/valuedomain/DV_KT_BEZ_GDE_SNAP/2024.1.0> .
```

- The class of `ap:concept`'s target says what was linked: value domain,
  data element concept, or data element.
- Evidence methods: `code-overlap`, `id-validator`, `rule` (described value
  domain), `embedding`, `llm` (with `ap:rationale`), `confirmed-elsewhere`
  (a person confirmed the same link for a slot with the same fingerprint).
- A person's match wins over an automatic one.
- The slot's SHACL shape is not touched: it keeps its column path and literal
  datatype.

## What the links make possible

Not part of the pipeline; shown here to check that the connections suffice.

```sparql
# Datasets comparable with <dataset> through shared value domains,
# with the number of its slots that have a counterpart
SELECT ?other (COUNT(DISTINCT ?s1) AS ?sharedSlots) WHERE {
  <dataset> dcat:distribution/dcterms:conformsTo/dcterms:hasPart/sh:property ?s1 .
  ?s1 ap:valueDomain/dcterms:isVersionOf? ?vd .
  ?s2 ap:valueDomain/dcterms:isVersionOf? ?vd .
  ?other dcat:distribution/dcterms:conformsTo/dcterms:hasPart/sh:property ?s2 .
  FILTER(?other != <dataset>)
} GROUP BY ?other ORDER BY DESC(?sharedSlots)
```

The same query with `ap:dataElementConcept` gives semantically comparable
datasets, and with `ap:dataElement` those that are both.

## Graphs

| Graph | Source | Content | On rerun |
|---|---|---|---|
| `urn:data:auto-profiling-githubpipeline` | auto-profiling | structures, slots, observations | replaced |
| `urn:data:concept-matching-githubpipeline` | concept-matching | the registry (from `registry/` in the repo), candidates, automatic matches, shortcut triples | replaced; registry entries keep their IRIs because they come from the repo files |
| confirmations graph (name open) | `confirmations.csv` for now, a review UI later | matches made by a person | never replaced by a pipeline run |

## Fingerprints

A slot's fingerprint is a hash of its normalised name, datatype and value
sample. Code-list matching, lookups and LLM calls run once per fingerprint
and the result applies to every slot that shares it. This only saves work;
each slot still carries its own links.

## IRI stability

Slot IRIs derive from a hash of the structure's representative distribution,
so they change when the representative changes (fallback used, new export
format, distribution removed). That is accepted:

- **Candidates, automatic matches and shortcuts** are regenerated after every
  auto-profiling run; until this pipeline has run, some point at slots that
  no longer exist.
- **A person's matches** are not regenerated, so each one stores a
  **re-attach key**: the dataset IRI, the distribution IRIs of the slot's
  structure, the container name and the slot's source name. After every run
  a match whose slot IRI vanished is re-attached to the slot whose structure
  shares a distribution and whose container and source name are the same;
  those that cannot be placed are reported. Dataset plus source name alone is
  not a key: in the last run 20,617 of 27,677 slots shared it with another
  slot (one dataset has 54 structures).
- **Registry entries** never change their IRI.

## Linking to code lists

- **Local comparison.** The codes of all lists (list, version, level,
  notation) are fetched once from LINDAS into a DuckDB file in the pipeline's
  cache; one join compares every fingerprint's values with every list.
- **Normalise first:** trim, case, leading zeros, integer versus string.
  LINDAS notations are plain strings without padding (`261`, not `0261`).
- **containment:** share of the slot's distinct values found in one level of
  a list. **coverage:** share of that level's codes seen in the slot; low is
  normal for samples and subsets.
- **Automatic link only when unambiguous:** high containment, enough distinct
  values, and a clear lead over every other list. Overlap alone is often
  ambiguous: the values `1`, `2` fit sex, civil status and other lists at
  100%; 200 random integers between 1 and 6810 reach 28% on municipalities;
  municipality numbers also fit the agglomeration lists.
- **Ambiguous cases keep their candidates** and are decided by the LLM in the
  concept step, which sees the column's name and context.
- Among versions with equal containment the slot links to the list, not to a
  version.

## Finding or creating a concept

Per fingerprint:

1. Describe the slot: name, label, container, neighbouring slots, datatype,
   value sample, and its value domain if it has one.
2. Look up the nearest existing object classes and properties by embedding
   (local index of the registry's labels and definitions).
3. The LLM names the slot's object class and property, each as an existing
   entry (exact or close) or as a new one with label and definition; or
   answers "no concept". In the same call it picks among ambiguous code-list
   candidates. The data element concept follows by rule from the pair.
4. A value check drops answers the data contradicts (values outside the
   chosen code list).
5. New entries are written to `registry/` and are visible to the next lookup
   in the same run.

The result depends on the order of processing, and the lookup will sometimes
miss, so duplicates arise. They are merged later (pruning), with the replaced
entry pointing to its replacement.

## Vocabulary changes (metadata-swiss)

- Namespaces moved (see [01-purpose.md](01-purpose.md)).
- `ap:concept`: range `mdr:ValueDomain`, `mdr:DataElementConcept`,
  `mdr:DataElement`.
- New shortcut properties on `ap:Slot`: `ap:valueDomain`,
  `ap:dataElementConcept`, `ap:dataElement`; new `ap:fingerprint`. Object
  class and property are reached through the concept (`mdr:objectClass`,
  `mdr:property`).
- New `ap:evidence` with `ap:method`, `ap:containment`, `ap:coverage`,
  `ap:level`, `ap:rationale`; new `ap:matchType`.
- New properties on `ap:Match` for the re-attach key (dataset, distribution,
  container name, source name).
- `ap:mainObjectClass`: range `mdr:ObjectClass`, derived from the object
  classes of a container's concepts.
- `mdr-shapes.ttl`: a value domain may be a version of another
  (`dcterms:isVersionOf`); a data element concept may have the status
  "candidate" with provenance in place of a creator.

## Review findings (2026-11-10)

Checked against the last 500-dataset run, LINDAS and the I14Y API:

| Finding | Number |
|---|---|
| Slots (leaf fields) in the run | 27,677 (geo 64%, tabular 24%) |
| Distinct fingerprints | 8,761 |
| Distinct column names | 4,165; the 500 most common cover 68% of slots |
| Slots with stored values | 15,510; 6,931 slots with more than 50 distinct values have none |
| Slots with only small integer values (below 100) | 2,109 |
| Slots sharing (dataset, source name) with another slot | 20,617 |
| LINDAS overlap query, 200 values, grouped by scheme and level | 0.2 s |
| visoto templates or scripts using `prof:` | none |
