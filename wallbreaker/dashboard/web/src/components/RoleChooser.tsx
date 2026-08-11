import { useCallback, useEffect, useRef, useState } from "react";
import { api, type AgentProfile, type RoleAssignments, type RoleChoice } from "../api";
import { ModelChooser } from "./ModelChooser";
import { ProviderChooser } from "./ProviderChooser";
import { Dialog } from "../primitives/Dialog";

export function RoleChooser({
  role, value, onSaved,
}: {
  role: keyof Pick<RoleAssignments, "attacker" | "target" | "judge">;
  value: RoleChoice;
  onSaved: () => void;
}) {
  const root = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const [open, setOpen] = useState(false);
  const [provider, setProvider] = useState(value.provider);
  const [model, setModel] = useState(value.model);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [profiles, setProfiles] = useState<AgentProfile[]>([]);
  const [profile, setProfile] = useState(value.profile || "");
  useEffect(() => { setProvider(value.provider); setModel(value.model); setProfile(value.profile || ""); }, [value]);
  useEffect(() => { if (open) api.agentProfiles().then((data) => setProfiles(data.roles[role]?.profiles || [])).catch(() => setProfiles([])); }, [open, role]);
  const close = useCallback(() => setOpen(false), []);
  const save = async () => {
    if (!profile && (!provider || !model.trim())) return;
    setBusy(true); setError("");
    try { await api.saveRole(role, profile ? { profile } : { provider, model: model.trim() }); setOpen(false); onSaved(); }
    catch (err) { setError((err as Error).message); }
    finally { setBusy(false); }
  };
  return (
    <div className="role-chooser" ref={root}>
      <button ref={trigger} type="button" className="role-chip" onClick={() => setOpen(!open)} aria-expanded={open} aria-label={`${role} model chooser`}>
        <span>{role}</span><b>{value.model || "not set"}</b><small>{value.profile || `Custom · ${value.provider}`}</small>
      </button>
      <Dialog open={open} title={`Configure ${role}`} onClose={close}>
      <div className="role-menu">
        <label>Agent profile</label>
        <select aria-label={`${role} agent profile`} value={profile} onChange={(event) => {
          const next = event.target.value; setProfile(next);
          const selected = profiles.find((item) => item.name === next);
          if (selected) { setProvider(selected.provider); setModel(selected.model); }
        }}>
          <option value="">Custom</option>
          {profiles.map((item) => <option key={item.name} value={item.name}>{item.name}</option>)}
        </select>
        {!profile && <>
          <label>Provider</label>
          <ProviderChooser value={provider} ariaLabel={`${role} provider`} onChange={(next, item) => { setProvider(next); if (item) setModel(item.model); }} />
          <label>Model</label>
          <ModelChooser profile={provider} value={model} onChange={setModel} ariaLabel={`${role} model`} />
        </>}
        {error && <div className="err">{error}</div>}
        <button type="button" className="primary-command" disabled={busy || (!profile && !model.trim())} onClick={() => void save()}>Apply</button>
      </div>
      </Dialog>
    </div>
  );
}
