"""
Verify the new topic-fingerprint dedup system catches all duplicates.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from news_monitor import is_topic_duplicate, get_topic_fingerprint, clean_tokens

# ===== THE REAL PROBLEM: OpenAI sandbox articles from different sources =====
openai_titles = [
    "OpenAI-agent brød ud af isoleret sandbox under sikkerhedstest",
    "Kunstig intelligens: OpenAI's agent undslap sandkasse-miljøet",
    "Sikkerhedsforskere advarer: AI-model fra OpenAI bryder ud af kontrolleret miljø",
    "OpenAI indrømmer: Agent omgik sikkerhedsforanstaltninger i test",
    "Ny rapport: OpenAI-modellen forsøgte gentagne gange at undslippe sandbox",
]

# Unrelated articles that should NOT be caught
unrelated_titles = [
    "Dansk virksomhed lancerer ny cybersikkerhedsplatform",
    "Apple præsenterer iPhone 17 med ny chip",
    "Microsoft køber gaming-startup i København",
    "Ny EUD-reform giver flere IT-elevpladser i Midtjylland",
    "Google lancerer Gemini 3.0 til virksomheder",
    "OpenAI lancerer ny ChatGPT-funktion til kodning",  # Same entity, different event
]

print("=" * 70)
print("VERIFICATION: Topic fingerprint dedup system")
print("=" * 70)

print("\n--- OpenAI sandbox titles (should ALL be caught as duplicates) ---")
all_caught = True
for i, t1 in enumerate(openai_titles):
    fp = get_topic_fingerprint(t1)
    print(f"  [{i+1}] FP: {fp}")
    print(f"       Title: {t1[:70]}")
    for j, t2 in enumerate(openai_titles):
        if j <= i:
            continue
        result = is_topic_duplicate(t1, t2)
        status = "✅ CAUGHT" if result else "❌ MISSED!"
        if not result:
            all_caught = False
        print(f"       vs [{j+1}]: {status}")

if all_caught:
    print("\n  🎉 ALL DUPLICATES CAUGHT!")
else:
    print("\n  ⚠️  SOME DUPLICATES MISSED")

print("\n--- Unrelated titles (should NOT be flagged as duplicates) ---")
false_positives = False
for t in unrelated_titles:
    fp = get_topic_fingerprint(t)
    result = is_topic_duplicate(openai_titles[0], t)
    status = "❌ FALSE POSITIVE!" if result else "✅ OK"
    if result:
        false_positives = True
    print(f"  {status} | FP: {fp} | {t[:60]}")

if not false_positives:
    print("\n  🎉 NO FALSE POSITIVES!")
else:
    print("\n  ⚠️  FALSE POSITIVES DETECTED")

# Test empty title handling
print("\n--- Edge cases ---")
print(f"  Empty vs real: {is_topic_duplicate('', openai_titles[0])} (should be False)")
print(f"  None handling: {is_topic_duplicate('test', '')} (should be False)")
