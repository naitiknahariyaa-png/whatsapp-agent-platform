"""
CLI Tool — Command-line management for power users
"""
import json
import logging
import os
import sys
from typing import Optional, Dict, Any, List
from datetime import datetime

logger = logging.getLogger("cli_tool")


class CLIManager:
    """
    CLI commands for managing the platform via terminal.
    Provides interactive and non-interactive command support.
    """

    def __init__(self, api_key: Optional[str] = None,
                 api_base: str = "http://localhost:8000"):
        self.api_key = api_key or os.getenv("WAP_API_KEY", "")
        self.api_base = api_base
        self._client = None

    def _get_client(self):
        """Get or create HTTP client"""
        if not self._client:
            import httpx
            headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
            self._client = httpx.Client(
                base_url=self.api_base,
                headers=headers,
                timeout=30,
            )
        return self._client

    def cmd_health(self) -> Dict:
        """Check platform health"""
        try:
            client = self._get_client()
            resp = client.get("/health")
            return resp.json()
        except Exception as e:
            return {"status": "error", "error": str(e)}

    def cmd_send_message(self, phone: str, message: str, client_id: int = 1) -> Dict:
        """Send a message via the agent"""
        client = self._get_client()
        resp = client.post("/api/message", json={
            "phone_number": phone,
            "message": message,
            "client_id": client_id,
        })
        return resp.json()

    def cmd_list_leads(self, tier: Optional[str] = None, limit: int = 10) -> List[Dict]:
        """List leads, optionally filtered by tier"""
        client = self._get_client()
        params = {"limit": limit}
        if tier:
            params["tier"] = tier
        resp = client.get("/api/leads", params=params)
        return resp.json()

    def cmd_get_stats(self) -> Dict:
        """Get platform statistics"""
        client = self._get_client()
        resp = client.get("/stats")
        return resp.json()

    def cmd_list_campaigns(self) -> List[Dict]:
        """List drip campaigns"""
        from services.drip_campaigns import engine
        return [c.to_dict() for c in engine.campaigns.values()]

    def cmd_create_campaign(self, name: str, description: str = "") -> Dict:
        """Create a new drip campaign"""
        from services.drip_campaigns import DripCampaign, TriggerType, engine
        import hashlib

        campaign_id = hashlib.md5(f"{name}_{datetime.utcnow().timestamp()}".encode()).hexdigest()[:12]
        campaign = DripCampaign(
            id=campaign_id,
            name=name,
            description=description,
        )
        engine.register_campaign(campaign)
        return campaign.to_dict()

    def cmd_create_qr(self, phone: str, message: str = "") -> Dict:
        """Create a QR code"""
        from services.qr_generator import qr_manager
        qr = qr_manager.create(phone, message)
        return qr.to_dict()

    def cmd_broadcast(self, channel: str, contact_ids: List[str], message: str) -> Dict:
        """Send a broadcast message"""
        from services.multi_channel_hub import ChannelType, hub

        channel_map = {
            "whatsapp": ChannelType.WHATSAPP,
            "telegram": ChannelType.TELEGRAM,
            "sms": ChannelType.SMS,
            "email": ChannelType.EMAIL,
        }
        ch = channel_map.get(channel)
        if not ch:
            return {"error": f"Unknown channel: {channel}"}

        import asyncio
        results = asyncio.run(hub.broadcast(ch, contact_ids, message))
        return {"channel": channel, "sent": sum(1 for r in results.values() if r), "total": len(contact_ids)}

    def cmd_export_conversations(self, format: str = "jsonl") -> Optional[str]:
        """Export conversations as training data"""
        from services.ai_powerups import conversation_exporter
        # Get all conversations from the database
        import asyncio
        from db import get_session, get_conversation_history

        async def _export():
            conversations = []
            async for session in get_session():
                from db import Message
                from sqlalchemy import select
                result = await session.execute(
                    select(Message.phone_number).distinct()
                )
                phones = [r[0] for r in result.all()]

                for phone in phones[:10]:  # Limit to 10 contacts
                    msgs = await get_conversation_history(session, phone, limit=50)
                    conv = [{"content": m.content, "direction": m.direction} for m in msgs]
                    if conv:
                        conversations.append(conv)

            return await asyncio.to_thread(
                conversation_exporter.export_training_data,
                conversations,
                output_format=format,
            )

        return asyncio.run(_export())

    def run(self, args: Optional[List[str]] = None):
        """Run the CLI with command-line arguments"""
        if args is None:
            args = sys.argv[1:]

        if not args or args[0] in ("-h", "--help"):
            self._show_help()
            return

        command = args[0]
        cmd_args = args[1:]

        try:
            if command == "health":
                result = self.cmd_health()
            elif command == "send":
                if len(cmd_args) < 2:
                    print("Usage: wap send <phone> <message>")
                    return
                result = self.cmd_send_message(cmd_args[0], " ".join(cmd_args[1:]))
            elif command == "leads":
                tier = cmd_args[0] if cmd_args else None
                result = self.cmd_list_leads(tier)
            elif command == "stats":
                result = self.cmd_get_stats()
            elif command == "campaigns":
                result = self.cmd_list_campaigns()
            elif command == "create-campaign":
                if not cmd_args:
                    print("Usage: wap create-campaign <name> [description]")
                    return
                name = cmd_args[0]
                desc = " ".join(cmd_args[1:]) if len(cmd_args) > 1 else ""
                result = self.cmd_create_campaign(name, desc)
            elif command == "create-qr":
                if not cmd_args:
                    print("Usage: wap create-qr <phone> [message]")
                    return
                phone = cmd_args[0]
                msg = " ".join(cmd_args[1:]) if len(cmd_args) > 1 else ""
                result = self.cmd_create_qr(phone, msg)
            elif command == "broadcast":
                if len(cmd_args) < 3:
                    print("Usage: wap broadcast <channel> <contact_id1,contact_id2> <message>")
                    return
                channel = cmd_args[0]
                contacts = cmd_args[1].split(",")
                message = " ".join(cmd_args[2:])
                result = self.cmd_broadcast(channel, contacts, message)
            elif command == "export":
                fmt = cmd_args[0] if cmd_args else "jsonl"
                result = self.cmd_export_conversations(fmt)
            else:
                print(f"Unknown command: {command}")
                self._show_help()
                return

            print(json.dumps(result, indent=2, default=str))

        except Exception as e:
            print(f"Error: {e}")

    def _show_help(self):
        """Show CLI help"""
        print("""
╔══════════════════════════════════════════════════╗
║  WhatsApp Agent Platform — CLI v1.0              ║
╠══════════════════════════════════════════════════╣
║  Usage: wap <command> [options]                   ║
╠══════════════════════════════════════════════════╣
║  Commands:                                        ║
║    health                    Check platform health ║
║    send <phone> <msg>        Send a message        ║
║    leads [tier]              List leads            ║
║    stats                     Platform statistics   ║
║    campaigns                 List drip campaigns   ║
║    create-campaign <name>    Create a campaign     ║
║    create-qr <phone> [msg]   Create QR code        ║
║    broadcast <ch> <ids> <m>  Broadcast message     ║
║    export [format]           Export conversations  ║
║    -h, --help                Show this help        ║
╚══════════════════════════════════════════════════╝
""")


def main():
    """Entry point for the CLI"""
    cli = CLIManager()
    cli.run()


if __name__ == "__main__":
    main()