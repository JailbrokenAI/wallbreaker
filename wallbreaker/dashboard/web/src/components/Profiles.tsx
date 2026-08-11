import { useEffect, useRef, useState } from "react";
import { api, type AgentProfile, type AgentRole, type AgentProfilesResponse } from "../api";
import { ModelChooser } from "./ModelChooser";
import { ProviderChooser } from "./ProviderChooser";

const ROLES: AgentRole[] = ["attacker", "target", "judge"];
const blank = (role: AgentRole): AgentProfile => ({ name: "", role, provider: "", model: "", prompt_source: "none", system_prompt: "", system_prompt_file: "" });

export function Profiles({ onSaved }: { onSaved?: () => void }) {
  const [data, setData] = useState<AgentProfilesResponse | null>(null);
  const [editing, setEditing] = useState<Record<AgentRole, AgentProfile>>({ attacker: blank("attacker"), target: blank("target"), judge: blank("judge") });
  const [errors, setErrors] = useState<Partial<Record<AgentRole, string>>>({});
  const [busy, setBusy] = useState<Partial<Record<AgentRole, boolean>>>({});
  const busyRef = useRef<Partial<Record<AgentRole, boolean>>>({});
  const begin = (role: AgentRole) => {
    if (busyRef.current[role]) return false;
    busyRef.current = { ...busyRef.current, [role]: true };
    setBusy((value) => ({ ...value, [role]: true }));
    return true;
  };
  const end = (role: AgentRole) => {
    busyRef.current = { ...busyRef.current, [role]: false };
    setBusy((value) => ({ ...value, [role]: false }));
  };
  const load = () => api.agentProfiles().then(setData).catch((error) => setErrors({ attacker: (error as Error).message }));
  useEffect(() => { void load(); }, []);
  const change = (role: AgentRole, patch: Partial<AgentProfile>) => setEditing((current) => ({ ...current, [role]: { ...current[role], ...patch } }));
  const edit = (profile: AgentProfile) => change(profile.role, { ...profile });
  const save = async (role: AgentRole) => {
    if (!begin(role)) return;
    const item = editing[role]; setErrors((value) => ({ ...value, [role]: "" }));
    try {
      await api.saveAgentProfile(role, item.name.trim(), {
        provider: item.provider, model: item.model.trim(), prompt_source: item.prompt_source,
        system_prompt: item.prompt_source === "inline" ? item.system_prompt : "",
        system_prompt_file: item.prompt_source === "file" ? item.system_prompt_file.trim() : "",
      });
      change(role, blank(role)); load(); onSaved?.();
    } catch (error) { setErrors((value) => ({ ...value, [role]: (error as Error).message })); }
    finally { end(role); }
  };
  const remove = async (role: AgentRole, name: string) => {
    if (!begin(role)) return;
    try { await api.deleteAgentProfile(role, name); load(); onSaved?.(); }
    catch (error) { setErrors((value) => ({ ...value, [role]: (error as Error).message })); }
    finally { end(role); }
  };
  const activate = async (role: AgentRole, name: string) => {
    if (!begin(role)) return;
    try { await api.saveRole(role, { profile: name }); load(); onSaved?.(); }
    catch (error) { setErrors((value) => ({ ...value, [role]: (error as Error).message })); }
    finally { end(role); }
  };
  if (!data) return <div className="empty">Loading profiles…</div>;
  return <div className="agent-profile-grid">{ROLES.map((role) => {
    const roleData = data.roles[role]; const form = editing[role]; const roleBusy = !!busy[role];
    return <section className="card agent-profile-card" key={role}>
      <h3>{role} profiles</h3>
      <div className="profile-active mono">Active: <b>{roleData.active.profile || `Custom · ${roleData.active.provider}`}</b> · {roleData.active.model}</div>
      <div className="profile-list">{roleData.profiles.map((item) => <div className="profile-list-item" key={item.name}>
        <button type="button" className="profile-select" onClick={() => edit(item)}><b>{item.name}</b><span>{item.provider} · {item.model}</span><small>{item.prompt_source === "none" ? "No system prompt" : `${item.prompt_source} system prompt`}</small></button>
        <button type="button" className="mini-btn" disabled={roleBusy || roleData.active.profile === item.name} onClick={() => void activate(role, item.name)}>{roleData.active.profile === item.name ? "Active" : "Use"}</button>
        <button type="button" className="mini-btn" disabled={roleBusy} onClick={() => change(role, { ...item, name: `${item.name} copy` })}>Duplicate</button>
        <button type="button" className="mini-btn danger" disabled={roleBusy} onClick={() => void remove(role, item.name)}>Remove</button>
      </div>)}</div>
      <div className="profile-editor">
        <label className="fld">Profile name</label><input value={form.name} onChange={(e) => change(role, { name: e.target.value })} placeholder={`Named ${role} profile`} />
        <label className="fld">Provider</label><ProviderChooser value={form.provider} ariaLabel={`${role} provider`} onChange={(provider, item) => change(role, { provider, model: item?.model || form.model })} />
        <label className="fld">Model</label><ModelChooser profile={form.provider} value={form.model} onChange={(model) => change(role, { model })} placeholder="Choose or paste a model id" ariaLabel={`${role} profile model`} />
        <label className="fld">System prompt</label><select aria-label={`${role} system prompt source`} value={form.prompt_source} onChange={(e) => change(role, { prompt_source: e.target.value as AgentProfile["prompt_source"], system_prompt: "", system_prompt_file: "" })}><option value="none">None</option><option value="inline">Paste text</option><option value="file">Use file</option></select>
        {form.prompt_source === "inline" && <textarea className="profile-prompt" value={form.system_prompt} onChange={(e) => change(role, { system_prompt: e.target.value })} placeholder="Paste the agent system prompt" />}
        {form.prompt_source === "file" && <input value={form.system_prompt_file} onChange={(e) => change(role, { system_prompt_file: e.target.value })} placeholder="C:\\path\\to\\system-prompt.txt" />}
        {errors[role] && <div className="err">{errors[role]}</div>}
        <div className="profile-actions"><button className="primary-command" type="button" disabled={roleBusy || !form.name.trim() || !form.provider || !form.model.trim()} onClick={() => void save(role)}>Save profile</button><button className="mini-btn" type="button" disabled={roleBusy} onClick={() => change(role, blank(role))}>Clear</button></div>
      </div>
    </section>;
  })}</div>;
}
