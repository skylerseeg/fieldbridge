# Equipment Proposed Changes

## Dedicated Status Route

Request Lead wire a dedicated route to the existing equipment module page once
route ownership is available:

- Path: `/equipment/status`
- Component: `EquipmentPage`
- Initial tab/state: `status`
- Reason: field users need a direct bookmarkable URL for the Equipment Status
  Board while keeping the implementation inside
  `frontend/src/modules/equipment`.

Current worker-safe implementation exposes the Status Board as the default tab
inside `/equipment` and does not edit `frontend/src/routes.tsx`.
