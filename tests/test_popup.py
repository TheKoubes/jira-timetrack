from timetrack.popup import ghost_suffix, ticket_matches

TICKETS = ["ACMEREZ-298", "ACMEREZ-587", "DEMOERP-1215", "VEGAERP-861"]


class TestTicketMatches:
    def test_prefix_case_insensitive(self):
        assert ticket_matches("acme", TICKETS) == ["ACMEREZ-298", "ACMEREZ-587"]

    def test_uppercase_prefix(self):
        assert ticket_matches("DEMO", TICKETS) == ["DEMOERP-1215"]

    def test_no_match(self):
        assert ticket_matches("XYZ", TICKETS) == []

    def test_empty_text_offers_nothing(self):
        assert ticket_matches("", TICKETS) == []

    def test_space_stops_suggestions(self):
        # uz pise popis za klicem -> nenabizet
        assert ticket_matches("ACMEREZ-298 oprava", TICKETS) == []

    def test_fully_typed_key_offers_nothing(self):
        assert ticket_matches("ACMEREZ-298", TICKETS) == ["ACMEREZ-587"] or ticket_matches(
            "DEMOERP-1215", TICKETS
        ) == []

    def test_exact_key_alone_yields_empty(self):
        assert ticket_matches("DEMOERP-1215", TICKETS) == []


class TestGhostSuffix:
    def test_returns_tail(self):
        assert ghost_suffix("ACME", "ACMEREZ-298") == "REZ-298"

    def test_preserves_match_case_for_lowercase_input(self):
        assert ghost_suffix("acme", "ACMEREZ-298") == "REZ-298"

    def test_empty_when_not_a_prefix(self):
        assert ghost_suffix("DEMO", "ACMEREZ-298") == ""

    def test_empty_when_equal_length(self):
        assert ghost_suffix("ACMEREZ-298", "ACMEREZ-298") == ""
