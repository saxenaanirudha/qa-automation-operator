"""
Configuration loader utility.

Loads and caches ``config/config.yaml`` so that every module reads the same
central configuration without duplicating file-reading logic.
"""

import os
from typing import Any, Dict

import yaml

_CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "config.yaml"
)

_config_cache: Dict[str, Any] | None = None


def load_config(path: str | None = None) -> Dict[str, Any]:
    """
    Loads the YAML configuration file and caches the result.

    Args:
        path: Optional override path.  Defaults to ``config/config.yaml``.

    Returns:
        Parsed configuration dictionary.

    Raises:
        FileNotFoundError: If the configuration file does not exist.
    """
    global _config_cache
    if _config_cache is not None and path is None:
        return _config_cache

    config_path = path or _CONFIG_PATH
    if not os.path.exists(config_path):
        raise FileNotFoundError(f"Configuration file not found: {config_path}")

    with open(config_path, "r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)

    if path is None:
        _config_cache = data

    return data


def get_risk_config() -> Dict[str, Any]:
    """Returns the ``risk`` section of the configuration."""
    return load_config()["risk"]


def validate_quality_gate_config(cfg: Dict[str, Any]) -> None:
    """
    Validates Quality Gate configuration thresholds.

    Raises:
        ValueError: If any threshold relationship is invalid.
    """
    pr = cfg.get("pass_rate", {})
    if pr.get("fail_below", 0) > pr.get("warning_below", 0):
        raise ValueError(
            "Invalid quality gate configuration: pass_rate fail threshold cannot be higher than warning threshold."
        )

    fc = cfg.get("failure_count", {})
    if fc.get("fail_at", 0) < fc.get("warning_at", 0):
        raise ValueError(
            "Invalid quality gate configuration: failure_count fail threshold cannot be lower than warning threshold."
        )

    hr = cfg.get("high_risk_modules", {})
    if hr.get("fail_at", 0) < hr.get("warning_at", 0):
        raise ValueError(
            "Invalid quality gate configuration: high_risk_modules fail threshold cannot be lower than warning threshold."
        )

    nft = cfg.get("newly_failing_tests", {})
    if nft.get("fail_at", 0) < nft.get("warning_at", 0):
        raise ValueError(
            "Invalid quality gate configuration: newly_failing_tests fail threshold cannot be lower than warning threshold."
        )


def get_quality_gate_config() -> Dict[str, Any]:
    """
    Returns the ``quality_gate`` section of the configuration after validation.
    """
    cfg = load_config()["quality_gate"]
    validate_quality_gate_config(cfg)
    return cfg


def validate_flaky_detection_config(cfg: Dict[str, Any]) -> None:
    """
    Validates Flaky Test Detection configuration settings.

    Raises:
        ValueError: If configuration values or relationships are invalid.
    """
    min_obs = cfg.get("minimum_observations", 3)
    if min_obs < 2:
        raise ValueError(
            "Invalid flaky detection configuration: minimum_observations must be at least 2."
        )

    thresholds = cfg.get("thresholds", {})
    pos_flaky = float(thresholds.get("possibly_flaky", 25.0))
    flaky = float(thresholds.get("flaky", 50.0))

    if pos_flaky < 0 or flaky < 0:
        raise ValueError(
            "Invalid flaky detection configuration: thresholds must be non-negative."
        )

    if flaky > 100 or pos_flaky > 100:
        raise ValueError(
            "Invalid flaky detection configuration: thresholds cannot exceed 100."
        )

    if pos_flaky >= flaky:
        raise ValueError(
            "Invalid flaky detection configuration: possibly_flaky threshold must be lower than flaky threshold."
        )


def get_flaky_detection_config() -> Dict[str, Any]:
    """
    Returns the ``flaky_detection`` section of the configuration after validation.
    """
    cfg = load_config()["flaky_detection"]
    validate_flaky_detection_config(cfg)
    return cfg


def get_notification_config() -> Dict[str, Any]:
    """
    Returns the ``notifications`` section of the configuration.
    """
    return load_config().get("notifications", {})


def get_parser_config() -> Dict[str, Any]:
    """
    Returns the ``parser`` section of the configuration.
    """
    return load_config().get("parser", {})




