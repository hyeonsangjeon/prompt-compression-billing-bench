from copy import deepcopy
import unittest
from unittest.mock import patch

import src.cache_execution_figure as cache_figure
import src.swe_protocol_figure as swe_figure


class FollowUpFigureDisplayBindingTests(unittest.TestCase):
    def test_cache_display_count_mutation_is_rejected_in_both_languages(self):
        facts = cache_figure.load_facts()
        mutations = {
            "ko": "999개 유효 (관측)",
            "en": "999 valid (observed)",
        }
        for language, mutation in mutations.items():
            with self.subTest(language=language):
                display = deepcopy(cache_figure.build_display(facts, language))
                cards = list(display["cards"])
                name, plan, observations = cards[0]
                changed_observations = list(observations)
                changed_observations[1] = mutation
                cards[0] = (name, plan, tuple(changed_observations))
                display["cards"] = tuple(cards)
                with self.assertRaisesRegex(ValueError, "displayed facts"):
                    cache_figure.render_svg_from_display(facts, language, display)

    def test_swe_exit_and_quality_mutation_is_rejected_in_both_languages(self):
        facts = swe_figure.load_facts()
        mutations = {
            "ko": "종료 0 · 품질 통과",
            "en": "exit 0 · quality pass",
        }
        for language, mutation in mutations.items():
            with self.subTest(language=language):
                display = deepcopy(swe_figure.build_display(facts, language))
                outcomes = list(display["outcomes"])
                label, _ = outcomes[3]
                outcomes[3] = (label, (mutation,))
                display["outcomes"] = tuple(outcomes)
                with self.assertRaisesRegex(ValueError, "displayed facts"):
                    swe_figure.render_svg_from_display(facts, language, display)

    def test_in_memory_copy_mutations_cannot_bypass_the_display_contract(self):
        cases = (
            (cache_figure, "en", "999 valid (observed)"),
            (cache_figure, "ko", "유효 999개 (관측)"),
            (swe_figure, "en", "exit 0 · quality pass"),
            (swe_figure, "ko", "종료 0 · 품질 통과"),
        )
        for module, language, mutation in cases:
            with self.subTest(module=module.__name__, language=language):
                facts = module.load_facts()
                with patch.dict(module.COPY[language], {"title": mutation}):
                    with self.assertRaisesRegex(ValueError, "localized copy"):
                        module.render_svg(facts, language)

    def test_cache_accepted_fact_model_must_match_the_canonical_report(self):
        with patch.dict(cache_figure.FACTS["observed"], {"cycles_valid": 999}):
            with self.assertRaisesRegex(ValueError, "accepted facts"):
                cache_figure.load_facts()

    def test_swe_accepted_fact_model_must_match_the_canonical_report(self):
        with patch.dict(
            swe_figure.FACTS["statuses"],
            {"runner_exit": "0", "task_quality": "pass"},
        ):
            with self.assertRaisesRegex(ValueError, "accepted facts"):
                swe_figure.load_facts()


if __name__ == "__main__":
    unittest.main()
