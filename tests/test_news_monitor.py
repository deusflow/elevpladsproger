import unittest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from news_monitor import (
    is_topic_duplicate,
    classify_article_category,
    select_diverse_candidates,
    calculate_interest_score,
    clean_tokens,
    get_topic_fingerprint,
    extract_version_markers,
    KEY_ENTITIES,
    STOPWORDS,
    CATEGORY_KEYWORDS,
)


class TestEntityAndTokens(unittest.TestCase):
    """Test entity dictionary, stopwords, and token extraction."""

    def test_key_entities_expanded(self):
        self.assertGreaterEqual(len(KEY_ENTITIES), 100, f"KEY_ENTITIES should have >= 100 entities, has {len(KEY_ENTITIES)}")
        for essential in ["amd", "intel", "tsmc", "arm", "rust", "zig", "postgresql", "linux"]:
            self.assertIn(essential, KEY_ENTITIES, f"Essential entity '{essential}' missing from KEY_ENTITIES")

    def test_stopwords_contain_english_and_danish(self):
        for da in ["og", "i", "af", "på"]:
            self.assertIn(da, STOPWORDS, f"Danish stopword '{da}' missing")
        for en in ["the", "and", "for", "with", "that"]:
            self.assertIn(en, STOPWORDS, f"English stopword '{en}' missing")

    def test_extract_version_markers(self):
        markers = extract_version_markers("AMD Ryzen 9000 Zen 5 and Linux 6.14")
        self.assertIn("ryzen_9000", markers)
        self.assertIn("zen_5", markers)
        self.assertIn("linux_6.14", markers)

    def test_clean_tokens_strips_stopwords(self):
        tokens = clean_tokens("The new release of Linux kernel with Rust")
        self.assertNotIn("the", tokens)
        self.assertNotIn("with", tokens)
        self.assertIn("linux", tokens)
        self.assertIn("rust", tokens)

    def test_topic_fingerprint(self):
        fp = get_topic_fingerprint("NVIDIA RTX 5090 launches officially")
        entities = {t for t in fp if not t.startswith(("syn:", "ver:"))}
        self.assertIn("nvidia", entities)
        syns = {t for t in fp if t.startswith("syn:")}
        self.assertTrue(len(syns) > 0, "Expected launch synonym group in fingerprint")

    def test_category_keywords_coverage(self):
        expected_cats = {"systems_dev", "hardware_chips", "infosec", "gamedev_graphics", "ai_ml", "tech_trends"}
        self.assertEqual(set(CATEGORY_KEYWORDS.keys()), expected_cats)



class TestCrossLingualDedup(unittest.TestCase):
    """Test deduplication between English, Danish, and cross-lingual headlines."""

    def test_cross_lingual_hardware_release(self):
        # AMD Ryzen 9000 (EN) vs AMD lancerer Ryzen 9000 (DA)
        en = "AMD Ryzen 9000 Zen 5 CPUs officially unveiled"
        da = "AMD lancerer Ryzen 9000 processorer med Zen 5 arkitektur"
        self.assertTrue(is_topic_duplicate(en, da), f"Failed cross-lingual dedup: '{en}' vs '{da}'")

    def test_cross_lingual_gpu_announcement(self):
        # NVIDIA RTX 5090 (EN) vs NVIDIA præsenterer RTX 5090 (DA)
        en = "NVIDIA reveals next-gen RTX 5090 graphics card"
        da = "NVIDIA præsenterer RTX 5090 grafikkort med rekordhastighed"
        self.assertTrue(is_topic_duplicate(en, da), f"Failed cross-lingual dedup: '{en}' vs '{da}'")

    def test_cross_lingual_kernel_release(self):
        # Linux 6.14 kernel (EN) vs Linux 6.14 kernen (DA)
        en = "Linux 6.14 kernel released with new Rust drivers"
        da = "Linux 6.14 kernen udgivet med forbedret understøttelse"
        self.assertTrue(is_topic_duplicate(en, da), f"Failed kernel dedup: '{en}' vs '{da}'")

    def test_cross_lingual_layoffs(self):
        # Microsoft layoffs (EN) vs Microsoft fyrer (DA)
        en = "Microsoft announces 2000 layoffs in gaming division"
        da = "Microsoft fyrer 2000 medarbejdere i spilafdeling"
        self.assertTrue(is_topic_duplicate(en, da), f"Failed layoff dedup: '{en}' vs '{da}'")

    def test_cross_lingual_outage(self):
        # CrowdStrike outage (EN) vs CrowdStrike nedbrud (DA)
        en = "Massive CrowdStrike outage causes worldwide IT disruptions"
        da = "CrowdStrike nedbrud lammer it-systemer globalt"
        self.assertTrue(is_topic_duplicate(en, da), f"Failed outage dedup: '{en}' vs '{da}'")

    def test_en_to_en_different_publishers(self):
        # Tom's Hardware vs Ars Technica on TSMC
        en1 = "TSMC begins 2nm trial production for Apple chips"
        en2 = "TSMC enters 2nm volume fabrication targeting Apple"
        self.assertTrue(is_topic_duplicate(en1, en2), f"Failed EN-EN dedup: '{en1}' vs '{en2}'")

    def test_different_topics_same_entity_not_duplicate(self):
        # Two completely different news about Microsoft
        t1 = "Microsoft acquires cybersecurity startup for 500 million"
        t2 = "Microsoft releases Windows update fixing printer bug"
        self.assertFalse(is_topic_duplicate(t1, t2), f"False positive duplicate: '{t1}' vs '{t2}'")

    def test_different_entities_same_action_not_duplicate(self):
        # Two different companies releasing products
        t1 = "Apple unveils new M4 chip with neural engine"
        t2 = "Qualcomm announces Snapdragon X Elite processor"
        self.assertFalse(is_topic_duplicate(t1, t2), f"False positive duplicate: '{t1}' vs '{t2}'")


class TestCategoryClassification(unittest.TestCase):
    """Test 6-category IT classification."""

    def test_systems_dev(self):
        cat = classify_article_category("PostgreSQL 18 brings native JSONB vector search and Rust extensions")
        self.assertEqual(cat, "systems_dev")

        cat = classify_article_category("Linux kernel adds eBPF memory safety improvements written in Zig")
        self.assertEqual(cat, "systems_dev")

    def test_hardware_chips(self):
        cat = classify_article_category("TSMC starts 2nm mass production with EUV lithography for Apple and AMD")
        self.assertEqual(cat, "hardware_chips")

        cat = classify_article_category("Intel Arrow Lake Core Ultra CPUs benchmarked against AMD Ryzen 9000")
        self.assertEqual(cat, "hardware_chips")

    def test_infosec(self):
        cat = classify_article_category("Critical zero-day vulnerability in Linux kernel allows remote code execution")
        self.assertEqual(cat, "infosec")

        cat = classify_article_category("Researchers demonstrate side-channel attack bypassing post-quantum encryption")
        self.assertEqual(cat, "infosec")

    def test_gamedev_graphics(self):
        cat = classify_article_category("Unreal Engine 5.5 adds real-time neural path tracing and Nanite foliage")
        self.assertEqual(cat, "gamedev_graphics")

        cat = classify_article_category("Godot 4.4 beta debuts with Vulkan mobile renderer and WebGPU support")
        self.assertEqual(cat, "gamedev_graphics")

    def test_ai_ml(self):
        cat = classify_article_category("DeepSeek announces MoE architecture with 671B parameters and FP8 training")
        self.assertEqual(cat, "ai_ml")

        cat = classify_article_category("OpenAI releases reasoning model with test-time compute scaling")
        self.assertEqual(cat, "ai_ml")

    def test_tech_trends_fallback(self):
        cat = classify_article_category("Danish tech startup secures 15M euro funding for green datacenter")
        self.assertEqual(cat, "tech_trends")


class TestDiverseCandidateSelection(unittest.TestCase):
    """Test diverse candidate selection, category cooldown, and entity penalties."""

    def setUp(self):
        self.sample_articles = [
            {
                "title": "OpenAI announces new LLM model with vision capabilities",
                "description": "The new model achieves high scores on benchmarks",
                "link": "https://example.com/openai-llm",
                "interest_score": 12,
            },
            {
                "title": "PostgreSQL 18 internals: how the new query optimizer works",
                "description": "Deep dive into database architecture and query planning",
                "link": "https://example.com/postgres-18",
                "interest_score": 10,
            },
            {
                "title": "TSMC 2nm wafers entered trial production with high yield",
                "description": "Semiconductor manufacturing milestone for next-gen chips",
                "link": "https://example.com/tsmc-2nm",
                "interest_score": 11,
            },
            {
                "title": "Zero-day memory safety exploit found in Linux network stack",
                "description": "Kernel developers patch critical vulnerability",
                "link": "https://example.com/linux-0day",
                "interest_score": 9,
            },
            {
                "title": "Godot 4.4 brings WebGPU renderer and physics improvements",
                "description": "Open source game engine releases major update",
                "link": "https://example.com/godot-44",
                "interest_score": 10,
            },
        ]

    def test_diverse_selection_spreads_categories(self):
        state = {"posted_news_records": []}
        basket = select_diverse_candidates(self.sample_articles, state)
        categories = [a["category"] for a in basket]
        
        # All distinct categories should be represented
        unique_cats = set(categories)
        self.assertGreaterEqual(len(unique_cats), 4, f"Basket lacked diversity: {categories}")

    def test_cooldown_penalizes_recent_category(self):
        # If last post was ai_ml, ai_ml candidate should be de-prioritized
        state = {
            "posted_news_records": [
                {
                    "category": "ai_ml",
                    "entities": ["openai"],
                    "original_title": "OpenAI announces GPT-5",
                    "timestamp": 1000
                }
            ]
        }
        basket = select_diverse_candidates(self.sample_articles, state)
        # First article in basket should NOT be ai_ml
        self.assertNotEqual(basket[0]["category"], "ai_ml", "Cooldown failed: ai_ml was picked first immediately after ai_ml")

    def test_breaking_news_override(self):
        # Breaking news with score > 20 should survive cooldown
        breaking_article = {
            "title": "OpenAI breakthrough: AGI achieved with mathematical proof",
            "description": "Unprecedented achievement in neural network reasoning",
            "link": "https://example.com/openai-breakthrough",
            "interest_score": 24,
        }
        articles = [breaking_article] + self.sample_articles
        state = {
            "posted_news_records": [
                {
                    "category": "ai_ml",
                    "entities": ["openai"],
                    "original_title": "OpenAI launches feature",
                    "timestamp": 1000
                }
            ]
        }
        basket = select_diverse_candidates(articles, state)
        # Breaking news should still be retained and score high
        found = any(a["link"] == breaking_article["link"] for a in basket)
        self.assertTrue(found, "Breaking news override failed: article was excluded from basket")


class TestInterestScoring(unittest.TestCase):
    """Test that hardware, systems, gamedev, and AI receive balanced scores without blind spots."""

    def test_hardware_scores_high(self):
        score = calculate_interest_score("AMD Ryzen 9000 Zen 5 CPU launched with 4nm process")
        self.assertGreaterEqual(score, 4, f"Hardware should have score >= 4, got {score}")

    def test_systems_scores_high(self):
        score = calculate_interest_score("PostgreSQL 18 released with native vector indexing and distributed consensus")
        self.assertGreaterEqual(score, 4, f"Systems should have score >= 4, got {score}")

    def test_routine_incident_penalized(self):
        score = calculate_interest_score("Kommune ramt af phishing angreb: politiet advarer borgere")
        self.assertLessEqual(score, 0, f"Routine municipal incident should be <= 0, got {score}")


if __name__ == "__main__":
    unittest.main()
