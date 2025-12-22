# Location-Aware Store Proposal

## Overview

Add geographic awareness to AiogramShopBot with a **City -> Neighborhood** hierarchy that integrates with the existing N-level tree-based inventory system.

---

## Architecture Decision

### The Problem

We need two orthogonal dimensions:
- **Category Tree**: WHAT is being sold (Electronics -> Phones -> iPhone)
- **Location Tree**: WHERE it's available (New York -> Manhattan)

### Approaches Evaluated

| Approach | Description | Verdict |
|----------|-------------|---------|
| Extend Category Tree | Add locations as parents in category tree | **REJECTED** - Mixes concepts, inflexible |
| Location on Product | `Category.location_id` | **REJECTED** - Product can only exist in one location |
| **Parallel Location Tree** | Separate tree, Item-level association | **SELECTED** - Clean, flexible, proven pattern |

### Why Parallel Location Tree Wins

1. **Orthogonal Dimensions** - Category (WHAT) and Location (WHERE) are independent
2. **Proven Pattern Reuse** - Same tree structure as categories
3. **Flexibility** - Same product can exist in multiple locations
4. **Hierarchical Filtering** - Select city = see all neighborhoods' products

---

## Data Model

### New Table: `locations`

```python
class Location(Base):
    """
    Fixed 2-level hierarchy: City -> Neighborhood

    - parent_id = NULL: City (root)
    - parent_id != NULL: Neighborhood (leaf, is_deliverable=True)
    """
    __tablename__ = 'locations'

    id = Column(Integer, primary_key=True, unique=True)
    parent_id = Column(Integer, ForeignKey("locations.id", ondelete="CASCADE"), nullable=True)
    name = Column(String, nullable=False)
    is_deliverable = Column(Boolean, nullable=False, default=False)
    description = Column(String, nullable=True)

    parent = relationship(
        "Location",
        remote_side=[id],
        backref=backref("children", cascade="all, delete-orphan", passive_deletes=True)
    )

    __table_args__ = (
        CheckConstraint(
            '(parent_id IS NULL AND is_deliverable = 0) OR (parent_id IS NOT NULL AND is_deliverable = 1)',
            name='check_location_level_deliverable'
        ),
    )


class LocationDTO(BaseModel):
    id: int | None = None
    parent_id: int | None = None
    name: str | None = None
    is_deliverable: bool = False
    description: str | None = None
```

### Modified: `items` table

```python
# Add to Item model
location_id = Column(Integer, ForeignKey("locations.id", ondelete="RESTRICT"), nullable=False)
location = relationship("Location", backref="items")
```

### Modified: `users` table

```python
# Add to User model
preferred_location_id = Column(Integer, ForeignKey("locations.id"), nullable=True)
preferred_location = relationship("Location")
```

---

## Confirmed Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Location requirement | **MANDATORY** | Every item must have a location |
| Hierarchy depth | **FIXED 2 LEVELS** | City -> Neighborhood only |
| User experience | **LOCATION-FIRST** | User picks location, then browses filtered products |
| Filtering logic | **HIERARCHICAL** | City selection includes all neighborhoods |

---

## User Flow

```
FIRST LAUNCH
============
"Welcome! Select your city:"
[New York] [Los Angeles] [Chicago] ...

-> User picks "New York"
-> Stored: user.preferred_location_id = NYC.id


BROWSING (City-wide)
====================
+-- 📍 New York (all areas) [Change ▼] --+
|                                         |
|  Shows ALL products from:               |
|  - Manhattan                            |
|  - Brooklyn                             |
|  - Queens                               |
|  - etc.                                 |
+-----------------------------------------+


BROWSING (Neighborhood-specific)
================================
+-- 📍 Manhattan [Change ▼] -------------+
|                                         |
|  Shows ONLY Manhattan products          |
|                                         |
+-----------------------------------------+
```

---

## Hierarchical Filtering Logic

```python
async def get_deliverable_locations_under(location_id: int, session):
    """
    If location is a CITY -> returns all neighborhood IDs under it
    If location is a NEIGHBORHOOD -> returns just that neighborhood ID
    """
    cte_query = text("""
        WITH RECURSIVE location_tree AS (
            SELECT id, is_deliverable FROM locations WHERE id = :location_id
            UNION ALL
            SELECT l.id, l.is_deliverable FROM locations l
            INNER JOIN location_tree lt ON l.parent_id = lt.id
        )
        SELECT id FROM location_tree WHERE is_deliverable = 1
    """)
    result = await session_execute(cte_query, session, {"location_id": location_id})
    return {row[0] for row in result.fetchall()}
```

**Behavior:**
- User selects "New York" (city) -> Query returns [Manhattan_id, Brooklyn_id, Queens_id]
- User selects "Manhattan" (neighborhood) -> Query returns [Manhattan_id]

---

## Import Format Extension

### JSON Format (New)

```json
{
  "path": ["Electronics", "Phones", "iPhone"],
  "location_path": ["New York", "Manhattan"],
  "price": 999,
  "description": "iPhone 15 Pro",
  "private_data": "SERIAL-12345"
}
```

### TXT Format (New)

```
Electronics|Phones|iPhone;New York|Manhattan;999.0;iPhone 15 Pro;SERIAL-12345
```

---

## Implementation Phases

### Phase 1: Database Layer
1. Create `models/location.py` - Location model and DTO
2. Create `repositories/location.py` - Copy CategoryRepository pattern
3. Modify `models/item.py` - Add `location_id` column
4. Modify `models/user.py` - Add `preferred_location_id` column
5. Create migration script for schema changes

### Phase 2: Admin Location Management
6. Create `handlers/admin/location_management.py` - Admin handlers
7. Add `AdminLocationManagementCallback` to `callbacks.py`
8. Add location management to admin menu
9. Admin operations: Create city, Create neighborhood, Edit, Delete

### Phase 3: User Location Selection
10. Create `handlers/user/location_selection.py` - Location picker
11. Add location picker to My Profile
12. Force location selection if `preferred_location_id` is NULL
13. Add "📍 Location [Change]" header to category browsing

### Phase 4: Filtered Product Navigation
14. Modify `repositories/category.py` - Add location filter to queries
15. Modify `services/category.py` - Pass user's location to repository
16. Update stock-aware CTE:
    ```sql
    WHERE i.location_id IN (valid_location_ids) AND i.is_sold = 0
    ```

### Phase 5: Import Support
17. Modify `services/item.py` - Parse `location_path` in JSON
18. Modify `services/item.py` - Parse location in TXT format
19. Create `LocationRepository.get_or_create_path()` method

---

## Files to Create/Modify

| File | Action | Description |
|------|--------|-------------|
| `models/location.py` | CREATE | Location model + DTO |
| `models/item.py` | MODIFY | Add `location_id` FK |
| `models/user.py` | MODIFY | Add `preferred_location_id` FK |
| `repositories/location.py` | CREATE | Location repository |
| `services/location.py` | CREATE | Location service |
| `handlers/admin/location_management.py` | CREATE | Admin location handlers |
| `handlers/user/location_selection.py` | CREATE | User location picker |
| `callbacks.py` | MODIFY | Add location callbacks |
| `repositories/category.py` | MODIFY | Add location filtering |
| `services/category.py` | MODIFY | Pass location to repository |
| `services/item.py` | MODIFY | Support location in import |
| `handlers/user/all_categories.py` | MODIFY | Add location header + filter |
| `l10n/en.json` | MODIFY | Add location strings |
| `migrations/add_locations.py` | CREATE | Schema migration |

---

## Key Constraints

1. **Items MUST have location** - `location_id NOT NULL`
2. **Cities cannot be deliverable** - Enforced by CheckConstraint
3. **Neighborhoods must be deliverable** - Enforced by CheckConstraint
4. **No orphan items** - `ondelete="RESTRICT"` prevents deleting locations with items
5. **User must select location** - Forced on first interaction

---

## Database Constraints

```sql
-- Location level constraint
CHECK (
    (parent_id IS NULL AND is_deliverable = 0) OR
    (parent_id IS NOT NULL AND is_deliverable = 1)
)

-- Item must reference deliverable location
-- (enforced at application level)

-- Prevent deleting locations with items
FOREIGN KEY (location_id) REFERENCES locations(id) ON DELETE RESTRICT
```

---

## Estimated Effort

| Phase | Components | Complexity |
|-------|------------|------------|
| Phase 1 | Models, Repository | Medium (copy existing patterns) |
| Phase 2 | Admin handlers | Medium (copy inventory_management) |
| Phase 3 | User location picker | Low-Medium |
| Phase 4 | Filtered navigation | Medium (CTE modifications) |
| Phase 5 | Import support | Low |

**Total: Medium complexity** - Primarily copying and adapting existing patterns.
