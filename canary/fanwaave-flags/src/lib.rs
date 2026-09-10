#![forbid(unsafe_code)]

#[cfg(test)]
mod tests {
    use flags2env::BundledFlags2Env;
    use std::io::Write;
    use tempfile::NamedTempFile;

    fn audit(text: &str) -> Result<(), String> {
        let mut file = NamedTempFile::new().map_err(|error| error.to_string())?;
        file.write_all(text.as_bytes())
            .map_err(|error| error.to_string())?;
        let path = file
            .path()
            .to_str()
            .ok_or_else(|| "temporary contract path is not UTF-8".to_owned())?;
        BundledFlags2Env::new()
            .audit_config(Some(path))
            .map_err(|error| error.to_string())
    }

    #[test]
    fn current_strict_contract_syntax_is_admitted() {
        let current = r#"
[help]
url = "https://github.com/flags-2-env-test/sidecar-probe-e2e"

[env]
load = false

[parse]
allow_unknown = false

[flags.api-bind]
env = "FANWAAVE_API_BIND"
aliases = ["fanwaave-api-bind"]
type = "string"
help = "Fanwaave API bind."
"#;
        audit(current).expect("current strict syntax must be admitted");
    }

    #[test]
    fn stale_long_and_switch_keys_are_rejected() {
        let stale = r#"
[flags.api_bind]
env = "FANWAAVE_API_BIND"
long = "fanwaave-api-bind"
type = "string"

[flags.json]
env = "FANWAAVE_JSON"
long = "json"
switch = true
"#;
        let error = audit(stale).expect_err("stale syntax must fail closed");
        assert!(!error.is_empty());
    }

    #[test]
    fn unknown_fixed_section_key_is_rejected() {
        let stale = r#"
[parse]
allow_unknown = false
silently_accept_future_keys = true
"#;
        let error = audit(stale).expect_err("unknown fixed-section key must fail");
        assert!(!error.is_empty());
    }
}
