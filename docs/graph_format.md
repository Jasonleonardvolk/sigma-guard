# Graph JSON Format

SIGMA Guard accepts graph data as JSON. Here is the smallest valid graph:

```json
{
  "vertices": [
    {
      "id": "Policy",
      "claims": {
        "approved_vendor": "Supplier_A"
      }
    },
    {
      "id": "Procurement",
      "claims": {
        "approved_vendor": "Supplier_B"
      }
    }
  ],
  "edges": [
    {
      "source": "Policy",
      "target": "Procurement",
      "relation": "governs"
    }
  ]
}
```

## Field reference

### Vertices

| Field | Required | Description |
|---|---|---|
| `id` | yes | Unique node identifier |
| `label` | no | Display name (defaults to `id`) |
| `claims` | no | Key-value facts attached to this node |

Claims are the data SIGMA checks for consistency. Two adjacent
vertices with the same claim key but different values create
a potential structural contradiction.

### Edges

| Field | Required | Description |
|---|---|---|
| `source` | yes | Source vertex `id` |
| `target` | yes | Target vertex `id` |
| `relation` | no | Relationship label |

### Alternate field names

SIGMA Guard also accepts these alternate field names for compatibility
with other graph formats:

| Standard | Also accepted |
|---|---|
| `vertices` | `nodes` |
| `edges` | `links` |
| `source` | `from`, `src` |
| `target` | `to`, `tgt`, `dst` |
| `relation` | `type`, `label` |

## Other formats

SIGMA Guard also accepts:

- **GraphML** (.graphml): Standard XML graph format
- **Edge lists** (.edges, .tsv, .csv): Tab or comma separated,
  columns: source, target, relation, value

## Tips

- Use consistent claim keys across vertices that should agree.
  If one vertex uses `status` and another uses `state`, SIGMA
  will not detect a disagreement between them.
- Claims can be strings, numbers, or booleans.
- Vertices without claims are treated as neutral (no contradictions
  possible through them, but they participate in graph structure).
