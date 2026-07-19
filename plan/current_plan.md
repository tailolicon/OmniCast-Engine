# Plan - UI Acceptance Defect Fixes

We will execute the UI acceptance fixes by targeting the most critical layout, path mapping, and automation defects. To abide by the `Max Files: 3` constraint in this session, we will group our fixes into 3 primary files.

## Central ECC Skills Consulted
- `frontend-patterns`
- `design-system`
- `dashboard-builder`

## File Editing Matrix
1. **[MODIFY] [server.py](file:///E:/Project/OmniCast%20Engine/implementation/src/omnicast/api/server.py)**
   - Add policy scan metadata saving to `_run_policy_check_task`.
   - Add policy scan metadata retrieving to `get_policy`.
   - Add automatic pub-queueing approval generation on successful pipeline renders inside `_pipeline_handler`.
   - Expose scheduler properties (`enabled`, `shorts`, `upload`, `cadence`) in `get_channels`.
2. **[MODIFY] [render_routes.py](file:///E:/Project/OmniCast%20Engine/implementation/src/omnicast/api/render_routes.py)**
   - Expose dynamic script contents for `/api/products` and `/api/product/meta` requests.
   - Resolve product video and thumbnail paths relative to `/media/` using `_media_rel`.
   - Promote `width`, `height`, `fps`, and `created_at` fields to the top level of the metadata payload dynamically.
3. **[MODIFY] [Studio.tsx](file:///E:/Project/OmniCast%20Engine/implementation/frontend_v2/src/pages/Studio.tsx)**
   - Implement `isConfigDrawerOpen` state and render parameter accordions in a Drawer.
   - Replace office iframe with a fullscreen link button.
   - Embed Active Job progress card in the Left Column.
   - Dynamically load capability models from `/api/capabilities?kind=text` and `/api/capabilities?kind=image`.

## Verification Plan

### Automated Tests
- Run backend tests to verify no endpoint crashes:
  `pytest implementation/tests`
- Run frontend build checks to ensure type safety and successful bundling:
  `npm run build` inside `implementation/frontend_v2`

### Manual Verification
- Verify the Studio Left Column looks clean, has no vertical scroll bar, and the Drawer opens.
- Verify the office companion button functions correctly.
- Verify the video player and script text viewer in the Library load real content.
- Verify running a pipeline generates a publish approval in the queue automatically upon completion.
