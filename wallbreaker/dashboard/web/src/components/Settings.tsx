import { DaedalusOptions } from "./DaedalusOptions";
import { DesktopPanel } from "./DesktopPanel";
import { ModelPool } from "./ModelPool";
import { TargetOptions } from "./TargetOptions";

export function Settings({ onSaved }: { onSaved?: () => void }) {
  return (
    <div className="grid settings-grid">
      <div className="card settings-wide">
        <ModelPool onChanged={onSaved} />
      </div>
      <div className="card settings-wide">
        <DaedalusOptions />
      </div>
      <div className="card settings-wide">
        <TargetOptions />
      </div>
      <DesktopPanel />
    </div>
  );
}
