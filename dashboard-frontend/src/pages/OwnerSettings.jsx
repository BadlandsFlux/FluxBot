import { useSearchParams } from "react-router-dom";
import { Bot, Radio, Activity, Link2 } from "lucide-react";
import GuildSidebar from "../components/GuildSidebar";
import InviteSettingsTab from "../components/InviteSettingsTab";
import BotProfile from "./BotProfile";
import DiscordRelaySetup from "./DiscordRelaySetup";
import FluxerStatus from "./FluxerStatus";

const TABS = [
  { id: "bot-profile", label: "Bot Profile", icon: Bot, category: null },
  { id: "discord-relay", label: "Discord Relay", icon: Radio, category: null },
  { id: "fluxer-status", label: "Fluxer Status", icon: Activity, category: null },
  { id: "invite", label: "Invite Link", icon: Link2, category: null },
];

// Every owner-only, bot-wide (not per-server) setting lives under one
// page now rather than its own standalone route, same reasoning as
// GuildDetail's tabbed layout: these were three separate pages a
// server owner had to already know the URLs for, not discoverable
// from anywhere but the top bar's dropdown.
export default function OwnerSettings() {
  const [params, setParams] = useSearchParams();
  const tab = params.get("tab") || "bot-profile";

  function setTab(next) {
    setParams((p) => {
      p.set("tab", next);
      return p;
    });
  }

  return (
    <div className="guild-layout">
      <GuildSidebar tabs={TABS} activeTab={tab} onTabChange={setTab} counts={{}} />
      <div className="guild-main">
        <div className="page-head">
          <h1>Owner Settings</h1>
          <p className="muted">Bot-wide configuration, not scoped to any one server.</p>
        </div>
        <div className="tab-content" key={tab}>
          {tab === "bot-profile" && <BotProfile />}
          {tab === "discord-relay" && <DiscordRelaySetup />}
          {tab === "fluxer-status" && <FluxerStatus />}
          {tab === "invite" && <InviteSettingsTab />}
        </div>
      </div>
    </div>
  );
}
