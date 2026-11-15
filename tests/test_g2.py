"""G2 (blind8 A6, A13, A14): media/streaming facts, frontend and realtime coherence, IoT ingest sizing.
Each rule is tested on several project types plus inputs where it must not fire. Inputs are inline."""
import copy
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from engine.run import evaluate  # noqa: E402

BASE = {"scenario_id": "G2T", "project": {"type": "other", "platforms": ["web"], "description": "x"},
        "scale": {"users_at_launch": 800, "users_12_months": 6000, "peak_concurrent_users": 150},
        "team": {"size": 4, "experience": "intermediate", "languages": ["typescript", "python"], "has_devops": False},
        "budget": {"monthly_infra_usd": 3000}, "timeline": {"mvp_weeks": 16},
        "infrastructure": {"cloud_preference": "aws", "deployment_model": "managed_cloud", "data_residency": "none", "existing_systems": []},
        "requirements": {"auth": "email_password", "file_media_storage": True}}


def run(desc, typ="social", plats=("web",), **over):
    s = copy.deepcopy(BASE)
    s["project"].update(type=typ, platforms=list(plats), description=desc)
    for path, val in over.items():
        sec, key = path.split("__")
        s.setdefault(sec, {})[key] = val
    return evaluate(s, counterfactuals=False)


def sup(out):
    return out["stack"]["supporting"]


def choices(out, layer=None):
    return [s["choice"] for s in sup(out) if layer is None or s["layer"] == layer]


def codes(out):
    return [w["code"] for w in out["warnings"]]


class VideoPipeline(unittest.TestCase):
    def test_uploaded_video_gets_transcoder_queue_and_cdn(self):
        cases = (("social", "aws", "Recipe video platform: creators upload videos and we transcode them to adaptive streaming.", "MediaConvert"),
                 ("other", "gcp", "Course marketplace where teachers upload lecture videos; playback uses HLS on phones.", "Transcoder API"),
                 ("ecommerce", "aws", "Shop where sellers upload product videos that must play on slow mobile networks.", "MediaConvert"),
                 ("web_app", "azure", "Training portal: staff upload videos, converted to adaptive bitrate streaming.", "FFmpeg"))
        for typ, cloud, desc, tr in cases:
            with self.subTest(typ=typ):
                out = run(desc, typ, infrastructure__cloud_preference=cloud)
                self.assertTrue(any("Video transcoding" in c and tr in c for c in choices(out, "other")), choices(out))
                self.assertTrue(choices(out, "queue"), "a transcoding queue")
                self.assertTrue(choices(out, "cdn"), "a CDN")
                self.assertIn("videos", [s for s in sup(out) if s["layer"] == "storage"][0]["justification"])

    def test_azure_names_no_managed_transcoder(self):
        out = run("Training portal: staff upload videos, converted to adaptive bitrate streaming.", "web_app", infrastructure__cloud_preference="azure")
        t = [s for s in sup(out) if "Video transcoding" in s["choice"]][0]
        self.assertTrue(any("no managed transcoder for Azure" in x for x in t["tradeoffs"]))

    def test_video_without_upload_or_transcoding_does_not_fire(self):
        cases = (("other", "Small church website: service times and sermon videos embedded from YouTube."),
                 ("healthtech", "Clinic booking with video consultations between patient and doctor."),
                 ("content_site", "Blog about video games with reviews and news."))
        for typ, desc in cases:
            with self.subTest(desc=desc):
                out = run(desc, typ, requirements__file_media_storage=False)
                self.assertFalse(any("Video transcoding" in c for c in choices(out)), choices(out))


class LiveMedia(unittest.TestCase):
    def test_live_streaming_karaoke_and_webrtc_get_a_media_server(self):
        cases = (("social", "Live karaoke streaming with real-time duets and leaderboards."),
                 ("gaming", "Esports app with live streaming of matches and a WebRTC voice room per team."),
                 ("other", "Church that goes live every Sunday with live broadcast video to members."))
        for typ, desc in cases:
            with self.subTest(typ=typ):
                out = run(desc, typ, requirements__realtime=True)
                media = [c for c in choices(out, "realtime") if "Live audio/video" in c or "Video calls" in c]
                self.assertTrue(media, choices(out, "realtime"))

    def test_karaoke_is_named_live_media_not_video_calls(self):
        out = run("Live karaoke streaming with real-time duets.", "social", requirements__realtime=True)
        self.assertTrue(any(c.startswith("Live audio/video") for c in choices(out, "realtime")))

    def test_live_dashboards_and_scores_do_not_fire(self):
        cases = (("other", "Shows live scores and live dashboards of the league table."),
                 ("saas_b2b", "Operators watch live dashboards; deliveries are tracked on a map."),
                 ("social", "A forum where people discuss shows and duets of their favourite bands in threads."))
        for typ, desc in cases:
            with self.subTest(desc=desc):
                out = run(desc, typ, requirements__realtime=True)
                self.assertFalse([c for c in choices(out, "realtime") if "Live audio/video" in c or "Video calls" in c], choices(out, "realtime"))


class ReviewFixes(unittest.TestCase):
    def test_go_live_as_a_launch_date_and_text_broadcasts_do_not_fire(self):
        cases = (("social", "Recipe sharing for friends; we go live in March."),
                 ("other", "Newsletter that broadcasts results to subscribers."),
                 ("web_app", "Staff portal; the team goes live next quarter after the pilot."))
        for typ, desc in cases:
            with self.subTest(desc=desc):
                out = run(desc, typ, requirements__realtime=True)
                self.assertFalse([c for c in choices(out, "realtime") if "Live audio/video" in c or "Video calls" in c], choices(out, "realtime"))
        out = run("Creators go live on stream to followers.", "social", requirements__realtime=True)
        self.assertTrue([c for c in choices(out, "realtime") if "Live audio/video" in c])

    def test_transcode_without_video_wording_and_reads_without_a_unit_do_not_fire(self):
        out = run("Podcast app: we transcode uploaded audio to MP3.", "other", requirements__file_media_storage=True)
        self.assertFalse(any("Video transcoding" in c for c in choices(out)))
        out = run("Cable stock list: the tape reads every 3 meters on the drum.", "internal_tool", requirements__file_media_storage=False)
        self.assertFalse([c for c in choices(out, "other") if c.startswith("Device ingestion")])
        out = run("Data loggers: a reading every 30 s from each freezer.", "saas_b2b", requirements__file_media_storage=False)
        self.assertTrue([c for c in choices(out, "other") if c.startswith("Device ingestion")])

    def test_video_egress_upper_bound_is_priced_on_tiers_and_states_the_minutes(self):
        import engine.costreal as cr
        self.assertAlmostEqual(cr.tiered_egress(10_000), 900)
        self.assertAlmostEqual(cr.tiered_egress(2_500_000), 83_300)
        out = run("Video platform where creators upload videos.", "social", scale__users_12_months=5_000_000, scale__peak_concurrent_users=50000)
        line = [a for a in out["estimated_monthly_cost_usd"]["assumptions"] if a.startswith("Video egress")][0]
        self.assertIn("2-30 minutes of adaptive-bitrate video", line)
        self.assertRegex(line, r"\$0\.03 above|CloudFront pay-as-you-go transfer tiers|Front Door edge-to-client transfer tiers")  # p5 item 6

    def test_managed_realtime_service_drops_the_backplane_and_is_a_priced_azure_entry(self):
        out = run("Live order board for a restaurant chain.", "saas_b2b", infrastructure__cloud_preference="azure", team__languages=["go"],
                  scale__users_12_months=80000, scale__peak_concurrent_users=3000, requirements__realtime=True)
        rt = [s for s in sup(out) if s["layer"] == "realtime"][0]
        self.assertEqual((rt["deployment"], rt["provider"]), ("managed", "azure"))
        self.assertIn("billed per unit", rt["tradeoffs"][0])
        self.assertTrue(any("azure-web-pubsub/resource-faq" in u for u in rt["sources"]))
        cache = [s for s in sup(out) if s["layer"] == "cache"]
        self.assertTrue(not cache or "backplane" not in cache[0]["justification"])
        self.assertTrue([a for a in out["estimated_monthly_cost_usd"]["assumptions"] if a.startswith("realtime:") and "planning estimate" in a and "official-unverified" not in a])
        # a self-run realtime library keeps the backplane reasons
        gcp = run("Live order board for a restaurant chain.", "saas_b2b", infrastructure__cloud_preference="gcp", team__languages=["go"],
                  scale__users_12_months=80000, scale__peak_concurrent_users=3000, requirements__realtime=True)
        self.assertIn("backplane", [s for s in sup(gcp) if s["layer"] == "cache"][0]["justification"])

    def test_static_generator_exclusion_cites_its_driver_and_numbers_have_separators(self):
        out = run("Parking sensors feed live maps.", "iot", requirements__realtime=True, requirements__auth="none",
                  requirements__file_media_storage=False, team__languages=["go"])
        fe = out["stack"]["frontend"]
        self.assertNotIn("Hugo", fe["choice"])
        out = run("Inverters push readings every 30 s from rooftop sites.", "data_analytics", scale__workload="write_heavy",
                  scale__data_volume_gb_12_months=2500, requirements__file_media_storage=False, infrastructure__cloud_preference="gcp")
        line = [a for a in out["estimated_monthly_cost_usd"]["assumptions"] if a.startswith("Database")][0]
        self.assertIn("~2,500 GB", line)

    def test_download_quote_keeps_case_and_mod_files_are_files(self):
        st = [s for s in sup(run("Forum and file hub for mods with Downloads of up to a few GB per mod.", "social")) if s["layer"] == "storage"][0]
        self.assertIn("Downloads of up to a few GB", st["justification"])
        self.assertIn("ploads (files)", st["justification"])


class LargeDownloads(unittest.TestCase):
    def test_gigabyte_downloads_add_signed_urls_range_and_egress_advice(self):
        cases = (("social", "Forum and file hub for mods with downloads of up to a few GB per mod."),
                 ("content_site", "Open-data portal; dataset downloads of around 4 GB each."),
                 ("other", "Distributes game installers, each 3 GB per download, to players."))
        for typ, desc in cases:
            with self.subTest(typ=typ):
                st = [s for s in sup(run(desc, typ)) if s["layer"] == "storage"][0]
                self.assertIn("range requests", st["justification"])
                self.assertIn("signed URLs", st["justification"])
                self.assertTrue(any("egress" in t for t in st["tradeoffs"]))
                self.assertIn("project.description", st["driven_by"])
                self.assertTrue(any("r2/pricing" in u for u in st["sources"]))

    def test_small_downloads_and_ram_sizes_do_not_fire(self):
        cases = (("social", "Forum with downloads of PDF handouts."),
                 ("other", "Field app for phones with 2 GB RAM that downloads a small price list."),
                 ("content_site", "Blog where readers download one-page checklists."))
        for typ, desc in cases:
            with self.subTest(desc=desc):
                st = [s for s in sup(run(desc, typ)) if s["layer"] == "storage"]
                self.assertTrue(not st or "range requests" not in st[0]["justification"])


class FrontendAndRealtimeCoherence(unittest.TestCase):
    GO = dict(team__languages=["go"])

    def test_static_generator_not_used_for_realtime_signin_or_dynamic_apps(self):
        cases = (("iot", "Parking sensors feed live free-space maps and a warden console.", dict(requirements__realtime=True, requirements__auth="none")),
                 ("saas_b2b", "Team workspace with accounts.", dict(requirements__auth="email_password")),
                 ("content_site", "Club site where members log in and post comments.", dict(requirements__auth="email_password")))
        for typ, desc, over in cases:
            with self.subTest(typ=typ):
                out = run(desc, typ, requirements__file_media_storage=False, **self.GO, **over)
                fe = out["stack"]["frontend"]["choice"]
                self.assertNotIn("Hugo", fe)
                self.assertNotIn("Astro", fe)

    def test_pure_static_site_may_still_use_a_generator(self):
        out = run("Club news and opening hours.", "content_site", requirements__auth="none", requirements__file_media_storage=False, **self.GO)
        self.assertIn("Hugo", out["stack"]["frontend"]["choice"])

    def test_realtime_text_follows_the_chosen_service(self):
        big = dict(scale__users_12_months=80000, scale__peak_concurrent_users=3000, requirements__realtime=True)
        go = run("Live order board for a restaurant chain.", "saas_b2b", infrastructure__cloud_preference="azure", team__languages=["go"], **big)
        rt = [s for s in sup(go) if s["layer"] == "realtime"][0]
        self.assertIn("Web PubSub", rt["choice"])
        self.assertNotIn("from the same", rt["justification"])
        self.assertIn("holds the clients' WebSocket connections", rt["justification"])
        net = run("Live order board for a restaurant chain.", "saas_b2b", infrastructure__cloud_preference="azure", team__languages=["csharp"], **big)
        rt = [s for s in sup(net) if s["layer"] == "realtime"][0]
        self.assertIn("SignalR Service", rt["choice"])
        self.assertNotIn("from the same", rt["justification"])
        aws = run("Live order board for a restaurant chain.", "saas_b2b", infrastructure__cloud_preference="gcp", team__languages=["go"], **big)
        rt = [s for s in sup(aws) if s["layer"] == "realtime"][0]
        self.assertIn("from the same", rt["justification"])

    def test_existing_mqtt_broker_or_network_server_means_no_second_intake(self):
        desc = "City network of 5,000 parking sensors report state changes over LoRaWAN to a live map."
        for existing in (["Mosquitto 1.6 MQTT broker"], ["ChirpStack LoRaWAN network server"], ["EMQX MQTT broker", "Oracle 19c"]):
            with self.subTest(existing=existing):
                out = run(desc, "iot", requirements__realtime=True, infrastructure__existing_systems=existing)
                self.assertFalse([c for c in choices(out, "other") if c.startswith("Device ingestion")], choices(out, "other"))
                self.assertIn("SERVICE_NOT_ADDED", codes(out))

    def test_no_existing_intake_or_a_kafka_cluster_keeps_the_device_ingestion(self):
        desc = "City network of 5,000 parking sensors report state changes to a live map."
        for existing in ([], ["Apache Kafka cluster"], ["Oracle 19c database"]):
            with self.subTest(existing=existing):
                out = run(desc, "iot", requirements__realtime=True, infrastructure__existing_systems=existing)
                self.assertTrue([c for c in choices(out, "other") if c.startswith("Device ingestion")], choices(out, "other"))

    def test_backend_reason_names_no_feature_the_inputs_switched_off(self):
        out = run("Order log for a small bakery.", "internal_tool", ("android",), team__languages=[], team__experience="beginner",
                  requirements__auth="none", requirements__file_media_storage=False, budget__monthly_infra_usd=10)
        why = out["stack"]["backend"]["justification"]
        self.assertNotIn("Entra", why)
        self.assertNotIn("SQL Server", why)


class IngestSizing(unittest.TestCase):
    def test_equipment_that_pushes_readings_gets_device_ingestion(self):
        cases = (("data_analytics", "Monitoring of 5,000 rooftop PV sites: inverters push readings every 30 s."),
                 ("saas_b2b", "Cold-room data loggers upload a reading every minute for compliance reports."),
                 ("other", "Water pumps push readings every 10 s to a dashboard."))
        for typ, desc in cases:
            with self.subTest(typ=typ):
                out = run(desc, typ, scale__workload="write_heavy", scale__data_volume_gb_12_months=2500, requirements__file_media_storage=False)
                self.assertTrue([c for c in choices(out, "other") if c.startswith("Device ingestion")], choices(out, "other"))

    def test_database_is_sized_by_a_large_write_heavy_volume(self):
        out = run("Inverters push readings every 30 s from rooftop sites.", "data_analytics", scale__workload="write_heavy",
                  scale__data_volume_gb_12_months=2500, requirements__file_media_storage=False, infrastructure__cloud_preference="gcp")
        line = [a for a in out["estimated_monthly_cost_usd"]["assumptions"] if a.startswith("Database")][0]
        self.assertIn("Raised to the 'medium' tier", line)

    def test_write_heavy_rows_over_one_terabyte_get_an_ingest_queue_at_any_tier(self):
        cases = (("saas_b2b", "Event analytics for web shops: every page view is logged and aggregated."),
                 ("fintech", "Payment event log that records every card authorisation for audit."),
                 ("web_app", "Clickstream collector for marketing sites; every click is stored."))
        for typ, desc in cases:
            with self.subTest(typ=typ):
                out = run(desc, typ, scale__workload="write_heavy", scale__data_volume_gb_12_months=2000, requirements__file_media_storage=False)
                q = [s for s in sup(out) if s["layer"] == "queue"]
                self.assertTrue(q)
                self.assertIn("ngest buffer", q[0]["justification"])

    def test_small_volume_files_or_a_scada_historian_do_not_fire(self):
        out = run("Inverters push readings every 30 s from rooftop sites.", "data_analytics", scale__workload="write_heavy",
                  scale__data_volume_gb_12_months=50, requirements__file_media_storage=False, infrastructure__cloud_preference="gcp")
        self.assertFalse([a for a in out["estimated_monthly_cost_usd"]["assumptions"] if "Raised to the" in a])
        out = run("Photo archive: every upload is stored.", "web_app", scale__workload="write_heavy", scale__data_volume_gb_12_months=2000,
                  requirements__file_media_storage=True)
        self.assertFalse([s for s in sup(out) if s["layer"] == "queue" and "ngest buffer" in s["justification"]])
        out = run("Operations portal showing process readings from the plant's SCADA historian.", "internal_tool", scale__workload="read_heavy")
        self.assertFalse([c for c in choices(out, "other") if c.startswith("Device ingestion")])


if __name__ == "__main__":
    unittest.main()
