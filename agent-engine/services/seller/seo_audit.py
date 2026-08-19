import re
from typing import Dict, List
from db import SellerListing


async def audit_listing(listing: SellerListing) -> Dict:
    issues = []
    suggestions = []
    score = 100.0

    title = listing.title or ""
    bullets = listing.bullets or ""
    description = listing.description or ""
    keywords = listing.backend_keywords or ""

    if not title:
        issues.append("Missing title")
        score -= 30
    else:
        if len(title) < 50:
            issues.append("Title too short (< 50 chars)")
            score -= 10
        if len(title) > 200:
            issues.append("Title too long (> 200 chars)")
            score -= 10

    if not bullets:
        issues.append("Missing bullet points")
        score -= 20
    else:
        bullet_list = [b.strip() for b in bullets.split("\n") if b.strip()]
        if len(bullet_list) < 3:
            issues.append("Less than 3 bullet points")
            score -= 10
        if len(bullet_list) > 5:
            issues.append("More than 5 bullet points (Amazon limits to 5)")
            score -= 5

    if not description:
        issues.append("Missing description")
        score -= 15
    elif len(description) < 100:
        issues.append("Description too short (< 100 chars)")
        score -= 10

    if not keywords:
        issues.append("Missing backend keywords")
        score -= 15

    stop_words = {"the","a","an","is","are","was","were","be","been","being","have","has","had","do","does","did","will","would","could","should","may","might","must","shall","can","need","dare","ought","used","to","of","in","for","on","with","at","by","from","as","into","through","during","before","after","above","below","between","out","off","over","under","again","further","then","once","here","there","when","where","why","how","all","each","every","both","few","more","most","other","some","such","no","nor","not","only","own","same","so","than","too","very","just","because","but","and","or","if","while","although","though","even","until","since","whether"}

    def extract_keywords(text: str) -> List[str]:
        words = re.findall(r'\b[a-zA-Z]{3,}\b', text.lower())
        return [w for w in words if w not in stop_words and len(w) > 2]

    title_kw = extract_keywords(title)
    bullet_kw = extract_keywords(bullets)
    desc_kw = extract_keywords(description)
    all_text_kw = list(set(title_kw + bullet_kw + desc_kw))

    backend_kw = [k.strip().lower() for k in keywords.split(",") if k.strip()]
    keywords_found = [k for k in backend_kw if k in all_text_kw]
    keywords_missing = [k for k in backend_kw if k not in all_text_kw]

    if keywords_missing:
        issues.append(f"{len(keywords_missing)} backend keywords not found in listing text")
        score -= min(15, len(keywords_missing) * 2)

    if not suggestions:
        suggestions.append("Listing looks good!")

    score = max(0, min(100, score))

    return {
        "score": round(score, 2),
        "issues": issues,
        "suggestions": suggestions,
        "keywords_found": keywords_found[:20],
        "keywords_missing": keywords_missing[:20],
    }
