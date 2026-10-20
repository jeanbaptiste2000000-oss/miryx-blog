import unittest

from scripts.trendjacking import FALLBACK_TIPS, complete_tips


class EditorialFallbackTests(unittest.TestCase):
    def test_partial_tip_lists_are_completed_in_all_languages(self):
        for lang in ("fr", "en", "ar"):
            with self.subTest(lang=lang):
                tips = complete_tips(lang, ["A useful concrete text-message tip that is long enough."])
                self.assertEqual(len(tips), 3)
                self.assertTrue(all(20 <= len(tip) <= 240 for tip in tips))

    def test_empty_tip_list_is_not_fabricated(self):
        self.assertEqual(complete_tips("fr", []), [])

    def test_complete_tip_list_is_preserved(self):
        tips = ["First concrete advice is long enough.", "Second concrete advice is long enough.",
                "Third concrete advice is long enough."]
        self.assertEqual(complete_tips("fr", tips), tips)

    def test_fallback_pool_exists_for_every_published_language(self):
        self.assertEqual(set(FALLBACK_TIPS), {"fr", "en", "ar"})
        self.assertTrue(all(len(items) >= 3 for items in FALLBACK_TIPS.values()))


if __name__ == "__main__":
    unittest.main()
