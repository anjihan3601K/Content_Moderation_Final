from io import BytesIO

from PIL import Image

from src.utils.tools import analyze_uploaded_image


def test_analyze_uploaded_image_returns_valid_metrics():
    image = Image.new("RGB", (100, 100), color=(255, 0, 0))
    buffer = BytesIO()
    image.save(buffer, format="PNG")

    result = analyze_uploaded_image(buffer.getvalue(), "test.png")

    assert result["valid"] is True
    assert result["width"] == 100
    assert result["height"] == 100
    assert result["risk_score"] >= 0.0
    assert result["risk_level"] in {"none", "low", "medium", "high", "severe"}
