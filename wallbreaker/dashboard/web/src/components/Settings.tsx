import { useEffect, useState } from "react";
import { api, type RoleAssignments } from "../api";
import { ProviderManager } from "./ProviderManager";
import { RoleChooser } from "./RoleChooser";
import { TargetOptions } from "./TargetOptions";

export function Settings({ onSaved }: { onSaved?: () => void }) {
  const [revision, setRevision] = useState(0);
  const [roles, setRoles] = useState<RoleAssignments | null>(null);
  const refreshRoles = () => { api.roles().then((value) => { setRoles(value); onSaved?.(); }).catch(() => setRoles(null)); };
  useEffect(() => { api.roles().then(setRoles).catch(() => setRoles(null)); }, []);
  return <div className="grid settings-grid" key={revision}>
    <div className="card settings-wide">
      <ProviderManager onChanged={() => { setRevision((value) => value + 1); onSaved?.(); }} />
    </div>
    <div className="card settings-wide muted settings-note">
      Provider connections own URLs, credentials, protocols, and model directories. Assign providers to attacker,
      target, and judge agents below or create reusable assignments on the Profiles page.
    </div>
    <div className="card settings-wide">
      <h3>Active agents</h3>
      <div className="settings-role-row">
        {roles && (["attacker", "target", "judge"] as const).map((role) => <RoleChooser key={role} role={role} value={roles[role]} onSaved={refreshRoles} />)}
      </div>
      <div className="muted settings-note settings-note-spaced">Quickly apply a named profile or a Custom provider/model assignment. Create and edit named profiles on the Profiles page.</div>
    </div>
    <div className="card settings-wide"><TargetOptions /></div>
  </div>;
}
