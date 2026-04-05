from ranking.v3.lanes import detect_active_lanes, LANE_REGISTRY


def test_vivek_activates_innovation_iot_lanes():
    resume_text = "Prototyping smart IoT devices with embedded sensors, MQTT automation, and conversational AI systems in an R&D lab"
    target_roles = ["Innovation Lead", "Prototype Engineer"]
    lanes = detect_active_lanes(resume_text, target_roles, current_focus=None)
    assert "innovation" in lanes
    assert "iot" in lanes


def test_aditya_activates_network_lane():
    resume_text = "Configured Cisco firewalls and Juniper routing, network automation with Ansible"
    target_roles = ["Network Engineer"]
    lanes = detect_active_lanes(resume_text, target_roles, current_focus=None)
    assert "network" in lanes
    assert "innovation" not in lanes


def test_example_no_special_lanes():
    resume_text = "Machine learning engineer with PyTorch, deep learning, data pipelines"
    target_roles = ["ML Engineer", "AI Platform Engineer"]
    lanes = detect_active_lanes(resume_text, target_roles, current_focus=None)
    assert lanes == []


def test_current_focus_overrides_resume():
    resume_text = "Software engineer with Java and Spring Boot"
    target_roles = ["Backend Engineer"]
    lanes = detect_active_lanes(resume_text, target_roles, current_focus="network automation firewall")
    assert "network" in lanes


def test_single_generic_innovation_term_does_not_activate_lane():
    resume_text = "Awards and achievements: innovation prize for AI automation"
    target_roles = ["Software Engineer"]
    lanes = detect_active_lanes(resume_text, target_roles, current_focus=None)
    assert "innovation" not in lanes


def test_sap_resume_activates_sap_lane():
    resume_text = "SAP SD consultant with SAP MM and SAP GTS on S/4HANA order to cash flows"
    target_roles = ["SAP SD Consultant"]
    lanes = detect_active_lanes(resume_text, target_roles, current_focus=None)
    assert "sap_erp" in lanes


def test_lane_registry_has_required_lanes():
    for name in ("innovation", "iot", "conversational_ai", "network", "r_and_d", "sap_erp"):
        assert name in LANE_REGISTRY


def test_each_lane_has_required_fields():
    for name, lane in LANE_REGISTRY.items():
        assert hasattr(lane, "detection_keywords"), name
        assert hasattr(lane, "query_templates"), name
        assert hasattr(lane, "must_have_terms"), name
        assert hasattr(lane, "negative_terms"), name
        assert hasattr(lane, "weight_overrides"), name
