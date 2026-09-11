"""
External tools and utilities for content moderation.

This module provides helper functions used by moderation agents.
Includes both keyword-based and ML-based detection methods.
"""

import re
import random
from io import BytesIO
from typing import Dict, Any
from datetime import datetime
import logging

from PIL import Image, UnidentifiedImageError

logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)

# ML Classifier integration
def get_ml_classifier():
    """Get or initialize the ML classifier (lazy loading)."""
    try:
        from ..ml.ml_classifier import get_ml_classifier as get_classifier
        return get_classifier()
    except Exception as e:
        logger.warning(f"ML classifier not available: {e}")
        return None


def score_media_urls(media_urls: list[str], media_type: str = "image") -> Dict[str, Any]:
    """Score media URLs for likely unsafe visual/audio content using filename heuristics."""
    if not media_urls:
        return {
            "risk_score": 0.0,
            "risk_level": "none",
            "signals": [],
            "media_type": media_type,
            "url_count": 0,
        }

    risky_terms = {
        "image": ["nsfw", "nude", "nudity", "sexual", "explicit", "porn", "gore", "blood", "violent", "weapon"],
        "video": ["gore", "violent", "blood", "attack", "weapon", "explicit", "porn", "nsfw", "fights"],
        "audio": ["abuse", "hate", "threat", "insult", "violent", "harassment"],
    }

    signals = []
    normalized = [str(url).lower() for url in media_urls]
    for url in normalized:
        for term in risky_terms.get(media_type, risky_terms["image"]):
            if term in url:
                signals.append(term)

    score = min(0.9, 0.25 * max(1, len(signals)) + 0.15 * len(normalized))
    if score >= 0.75:
        risk_level = "severe"
    elif score >= 0.5:
        risk_level = "high"
    elif score >= 0.3:
        risk_level = "medium"
    elif score > 0.0:
        risk_level = "low"
    else:
        risk_level = "none"

    return {
        "risk_score": round(score, 3),
        "risk_level": risk_level,
        "signals": sorted(set(signals)),
        "media_type": media_type,
        "url_count": len(normalized),
    }


def analyze_uploaded_image(file_bytes: bytes, filename: str = "upload.jpg") -> Dict[str, Any]:
    """Analyze a real uploaded image and produce a risk score based on pixel content."""
    try:
        image = Image.open(BytesIO(file_bytes)).convert("RGB")
    except (UnidentifiedImageError, OSError, ValueError):
        return {
            "valid": False,
            "error": "Invalid image file",
            "risk_score": 0.0,
            "risk_level": "none",
            "width": 0,
            "height": 0,
            "format": "unknown",
            "is_unsafe": False,
        }

    width, height = image.size
    pixels = list(image.getdata())
    total_pixels = len(pixels)
    if total_pixels == 0:
        return {
            "valid": False,
            "error": "Image is empty",
            "risk_score": 0.0,
            "risk_level": "none",
            "width": width,
            "height": height,
            "format": filename.rsplit('.', 1)[-1].lower() if '.' in filename else "unknown",
            "is_unsafe": False,
        }

    skin_pixels = 0
    bright_pixels = 0
    dark_pixels = 0
    saturated_pixels = 0

    for r, g, b in pixels:
        max_channel = max(r, g, b)
        min_channel = min(r, g, b)
        if r > 95 and g > 40 and b > 20 and (r - g) > 15 and max_channel - min_channel > 15:
            skin_pixels += 1
        if (r + g + b) / 3 > 200:
            bright_pixels += 1
        if (r + g + b) / 3 < 60:
            dark_pixels += 1
        if r > 180 and g < 120 and b < 120:
            saturated_pixels += 1

    skin_ratio = skin_pixels / total_pixels
    bright_ratio = bright_pixels / total_pixels
    dark_ratio = dark_pixels / total_pixels
    saturated_ratio = saturated_pixels / total_pixels

    # Conservative rule-based score based on actual image pixels.
    risk_score = min(1.0, 0.25 + (skin_ratio * 1.5) + (saturated_ratio * 1.2) + (dark_ratio * 0.2) + (bright_ratio * 0.1))

    if risk_score >= 0.8:
        risk_level = "severe"
    elif risk_score >= 0.6:
        risk_level = "high"
    elif risk_score >= 0.35:
        risk_level = "medium"
    elif risk_score > 0.0:
        risk_level = "low"
    else:
        risk_level = "none"

    return {
        "valid": True,
        "filename": filename,
        "width": width,
        "height": height,
        "format": filename.rsplit('.', 1)[-1].lower() if '.' in filename else "unknown",
        "risk_score": round(risk_score, 3),
        "risk_level": risk_level,
        "is_unsafe": risk_score >= 0.6,
        "skin_ratio": round(skin_ratio, 4),
        "bright_ratio": round(bright_ratio, 4),
        "dark_ratio": round(dark_ratio, 4),
        "saturated_ratio": round(saturated_ratio, 4),
    }


def analyze_text_sentiment(text: str) -> Dict[str, Any]:
    """
    Analyze sentiment of text content.

    Args:
        text: Content text to analyze

    Returns:
        Dictionary with sentiment and score
    """
    # Simplified sentiment analysis (in production, use proper NLP library)
    positive_words = ['love', 'great', 'awesome', 'excellent', 'good', 'happy', 'wonderful', 'amazing']
    negative_words = ['hate', 'bad', 'terrible', 'awful', 'horrible', 'disgusting', 'worst', 'pathetic']

    text_lower = text.lower()
    positive_count = sum(1 for word in positive_words if word in text_lower)
    negative_count = sum(1 for word in negative_words if word in text_lower)

    if positive_count > negative_count:
        sentiment = "positive"
        score = min(0.5 + (positive_count * 0.1), 1.0)
    elif negative_count > positive_count:
        sentiment = "negative"
        score = max(-0.5 - (negative_count * 0.1), -1.0)
    else:
        sentiment = "neutral"
        score = 0.0

    return {
        "sentiment": sentiment,
        "score": score
    }


def detect_toxicity(text: str, use_ml: bool = True) -> Dict[str, Any]:
    """
    Detect toxic language in text using ML models with keyword fallback.

    Args:
        text: Content text to analyze
        use_ml: Whether to try ML-based detection first (default: True)

    Returns:
        Dictionary with toxicity score and categories
    """
    # Try ML-based detection first
    if use_ml:
        classifier = get_ml_classifier()
        if classifier:
            try:
                ml_result = classifier.predict_toxicity(text)
                # Add keyword counts for compatibility
                from ..ml.keyword_detectors import keyword_toxicity_detection
                keyword_result = keyword_toxicity_detection(text)
                ml_result["profanity_count"] = keyword_result["profanity_count"]
                ml_result["insult_count"] = keyword_result["insult_count"]
                ml_result["threat_count"] = keyword_result["threat_count"]
                return ml_result
            except Exception as e:
                logger.error(f"ML toxicity detection failed, using fallback: {e}")

    # Fallback to keyword-based detection
    from ..ml.keyword_detectors import keyword_toxicity_detection
    return keyword_toxicity_detection(text)


def detect_hate_speech_patterns(text: str, use_ml: bool = True) -> Dict[str, Any]:
    """
    Detect hate speech patterns using ML models with keyword fallback.

    Args:
        text: Content text to analyze
        use_ml: Whether to try ML-based detection first (default: True)

    Returns:
        Dictionary with detection results
    """
    # Try ML-based detection first
    if use_ml:
        classifier = get_ml_classifier()
        if classifier:
            try:
                ml_result = classifier.predict_hate_speech(text)
                return {
                    "detected": ml_result.get("is_hate_speech", False),
                    "score": ml_result.get("hate_score", 0.0),
                    "patterns": ml_result.get("patterns", []),
                    "confidence": ml_result.get("confidence", 0.8),
                    "detection_method": ml_result.get("detection_method", "ml")
                }
            except Exception as e:
                logger.error(f"ML hate speech detection failed, using fallback: {e}")

    # Fallback to keyword-based detection
    from ..ml.keyword_detectors import keyword_hate_speech_detection
    return keyword_hate_speech_detection(text)


def check_policy_violations(
    content_text: str,
    content_type: str,
    user_reputation: float,
    toxicity_score: float
) -> Dict[str, Any]:
    """
    Check content against community policies.

    Args:
        content_text: Content to check
        content_type: Type of content
        user_reputation: User's reputation score
        toxicity_score: Toxicity score from detection

    Returns:
        Dictionary with violations and severity
    """
    violations = []
    flags = []
    severity = "none"

    text_lower = content_text.lower()

    # Check for hate speech policy
    hate_indicators = ['hate', 'supremacist', 'inferior']
    if any(ind in text_lower for ind in hate_indicators):
        violations.append("hate_speech")
        severity = "high"

    # Check for harassment policy
    harassment_indicators = ['harass', 'stalk', 'threaten', 'kill yourself', 'kys']
    if any(ind in text_lower for ind in harassment_indicators):
        violations.append("harassment")
        severity = "high"

    # Check for violence policy
    violence_indicators = ['kill', 'murder', 'assault', 'attack', 'bomb']
    if any(ind in text_lower for ind in violence_indicators):
        violations.append("violence")
        severity = "high"

    # Check for spam (based on patterns)
    spam_indicators = [
        'click here', 'buy now', 'limited offer', 'act now',
        'guaranteed', 'free money', 'work from home'
    ]
    if sum(1 for ind in spam_indicators if ind in text_lower) >= 2:
        violations.append("spam")
        severity = "medium" if severity == "none" else severity

    # Check for sexual content
    sexual_indicators = ['sex', 'porn', 'nude', 'xxx']
    if any(ind in text_lower for ind in sexual_indicators):
        violations.append("sexual_content")
        severity = "medium" if severity == "none" else severity

    # Check for misinformation indicators
    misinfo_indicators = [
        'guaranteed cure', 'doctors don\'t want you to know',
        'secret truth', 'mainstream media lies'
    ]
    if any(ind in text_lower for ind in misinfo_indicators):
        violations.append("misinformation")
        flags.append("potential_misinformation")

    # Check for self-harm content
    self_harm_indicators = ['suicide', 'self harm', 'end it all', 'want to die']
    if any(ind in text_lower for ind in self_harm_indicators):
        violations.append("self_harm")
        severity = "critical"
        flags.append("urgent_review")

    # Adjust severity based on toxicity
    if toxicity_score > 0.8 and severity == "none":
        severity = "high"
    elif toxicity_score > 0.6 and severity == "none":
        severity = "medium"
    elif toxicity_score > 0.3 and severity == "none":
        severity = "low"

    # Adjust based on user reputation
    if user_reputation < 0.3 and len(violations) > 0:
        # Increase severity for low-reputation users
        if severity == "low":
            severity = "medium"
        elif severity == "medium":
            severity = "high"

    return {
        "violations": violations,
        "severity": severity,
        "flags": flags
    }


def check_spam_indicators(content_text: str, user_profile: Any) -> Dict[str, Any]:
    """
    Check for spam indicators.

    Args:
        content_text: Content to check
        user_profile: User profile information

    Returns:
        Dictionary with spam detection results
    """
    indicators = []
    spam_score = 0.0

    text_lower = content_text.lower()

    # Check for excessive links
    url_count = text_lower.count('http://') + text_lower.count('https://') + text_lower.count('www.')
    if url_count > 3:
        indicators.append("excessive_links")
        spam_score += 0.3

    # Check for promotional language
    promo_words = ['buy', 'sale', 'discount', 'offer', 'deal', 'cheap', 'free']
    promo_count = sum(1 for word in promo_words if word in text_lower)
    if promo_count >= 3:
        indicators.append("promotional_content")
        spam_score += 0.2

    # Check for repetitive characters
    if re.search(r'(.)\1{5,}', content_text):
        indicators.append("repetitive_characters")
        spam_score += 0.15

    # Check for new account spamming
    if user_profile.account_age_days < 7 and url_count > 0:
        indicators.append("new_account_with_links")
        spam_score += 0.25

    # Check for ALL CAPS
    if len(content_text) > 20 and content_text.isupper():
        indicators.append("all_caps")
        spam_score += 0.1

    spam_score = min(spam_score, 1.0)

    return {
        "is_spam": spam_score > 0.5,
        "spam_score": spam_score,
        "indicators": indicators
    }


def calculate_user_reputation(
    current_score: float,
    total_posts: int,
    total_violations: int,
    previous_warnings: int,
    previous_suspensions: int,
    account_age_days: int,
    current_violation_severity: str
) -> Dict[str, Any]:
    """
    Calculate updated user reputation score.

    Args:
        current_score: Current reputation score
        total_posts: Total number of posts
        total_violations: Total violations
        previous_warnings: Number of warnings
        previous_suspensions: Number of suspensions
        account_age_days: Account age in days
        current_violation_severity: Severity of current violation

    Returns:
        Dictionary with updated reputation metrics
    """
    # Start with current score
    new_score = current_score

    # Penalty for current violation
    violation_penalties = {
        "critical": -0.3,
        "high": -0.2,
        "medium": -0.1,
        "low": -0.05,
        "none": 0.0
    }
    new_score += violation_penalties.get(current_violation_severity, 0.0)

    # Factor in violation rate
    if total_posts > 0:
        violation_rate = total_violations / total_posts
        if violation_rate > 0.2:  # More than 20% violations
            new_score -= 0.15
        elif violation_rate > 0.1:
            new_score -= 0.1

    # Penalty for warnings and suspensions
    new_score -= (previous_warnings * 0.05)
    new_score -= (previous_suspensions * 0.15)

    # Bonus for account age (established users)
    if account_age_days > 365:
        new_score += 0.05
    elif account_age_days > 180:
        new_score += 0.03

    # Bonus for activity without violations
    if total_posts > 100 and total_violations == 0:
        new_score += 0.1

    # Clamp score between 0 and 1
    new_score = max(0.0, min(1.0, new_score))

    # Determine tier
    if new_score >= 0.85:
        tier = "veteran"
    elif new_score >= 0.7:
        tier = "trusted"
    elif new_score >= 0.5:
        tier = "new_user"
    elif new_score >= 0.3:
        tier = "flagged"
    elif new_score >= 0.1:
        tier = "suspended"
    else:
        tier = "banned"

    # Calculate risk score (inverse of reputation)
    risk_score = 1.0 - new_score

    # Increase risk for recent violations
    if current_violation_severity in ["critical", "high"]:
        risk_score = min(risk_score + 0.2, 1.0)

    return {
        "reputation_score": new_score,
        "tier": tier,
        "risk_score": risk_score,
        "trust_level": "high" if new_score > 0.7 else "medium" if new_score > 0.4 else "low"
    }


def generate_content_id() -> str:
    """Generate a unique content ID."""
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    random_suffix = random.randint(1000, 9999)
    return f"CNT-{timestamp}-{random_suffix}"


def generate_user_id() -> str:
    """Generate a unique user ID."""
    timestamp = datetime.now().strftime("%Y%m%d")
    random_suffix = random.randint(10000, 99999)
    return f"USR-{timestamp}-{random_suffix}"
