import os
import sys
import random
import inspect
import threading

from functools import partial
from tracer import Tracker, ExecutionTracer, ExpressionInspector

random.seed(42)
try:
    import numpy as np
    np.random.seed(42)
except ImportError:
    pass

_state = threading.local()

FAIL_TO_PASS_TESTS = {
    "django__django-10097": [
        "test_ascii_validator",
        "test_unicode_validator",
        "test_help_text",
        "test_validate",
        "test_validate_property",
        "test_named_urls",
        "test_help_text",
        "test_validate",
        "test_validate_custom_list",
        "test_header_disappears",
        "test_inactive_user",
        "test_known_user",
        "test_last_login",
        "test_no_remote_user",
        "test_unknown_user",
        "test_user_switch_forces_new_login",
        "test_header_disappears",
        "test_inactive_user",
        "test_known_user",
        "test_last_login",
        "test_no_remote_user",
        "test_unknown_user",
        "test_user_switch_forces_new_login",
        "test_header_disappears",
        "test_inactive_user",
        "test_known_user",
        "test_last_login",
        "test_no_remote_user",
        "test_unknown_user",
        "test_user_switch_forces_new_login",
        "test_https_login_url",
        "test_lazy_login_url",
        "test_login_url_with_querystring",
        "test_named_login_url",
        "test_remote_login_url",
        "test_remote_login_url_with_next_querystring",
        "test_standard_login_url",
        "test_success_url_allowed_hosts_safe_host",
        "test_success_url_allowed_hosts_same_host",
        "test_success_url_allowed_hosts_unsafe_host",
        "test_empty_password_validator_help_text_html",
        "test_get_default_password_validators",
        "test_get_password_validators_custom",
        "test_password_changed",
        "test_password_validators_help_text_html",
        "test_password_validators_help_text_html_escaping",
        "test_password_validators_help_texts",
        "test_validate_password",
        "test_header_disappears",
        "test_inactive_user",
        "test_known_user",
        "test_last_login",
        "test_no_remote_user",
        "test_unknown_user",
        "test_user_switch_forces_new_login",
        "test_redirect_to_login_with_lazy",
        "test_redirect_to_login_with_lazy_and_unicode",
        "test_header_disappears",
        "test_inactive_user",
        "test_known_user",
        "test_last_login",
        "test_no_remote_user",
        "test_unknown_user",
        "test_user_switch_forces_new_login",
        "test_custom",
        "test_default",
        "test_named",
        "test_remote",
        "test_header_disappears",
        "test_inactive_user",
        "test_known_user",
        "test_last_login",
        "test_no_remote_user",
        "test_unknown_user",
        "test_user_switch_forces_new_login",
        "test_default_logout_then_login",
        "test_logout_then_login_with_custom_login",
        "test_PasswordChangeDoneView",
        "test_PasswordResetChangeView",
        "test_PasswordResetCompleteView",
        "test_PasswordResetConfirmView_invalid_token",
        "test_PasswordResetConfirmView_valid_token",
        "test_PasswordResetDoneView",
        "test_PasswordResetView",
        "test_createcachetable_observes_database_router",
        "test_create_save_error",
        "test_model_multiple_choice_field_uuid_pk",
        "test_update_save_error",
        "test_extra_args",
        "test_cache_key_i18n_formatting",
        "test_cache_key_i18n_timezone",
        "test_cache_key_i18n_translation",
        "test_cache_key_i18n_translation_accept_language",
        "test_cache_key_no_i18n",
        "test_middleware",
        "test_middleware_doesnt_cache_streaming_response",
        "test_dates",
        "test_fields",
        "test_month_filter",
        "test_order_by",
        "test_simple",
        "test_password_change_done_fails",
        "test_password_change_done_succeeds",
        "test_password_change_fails_with_invalid_old_password",
        "test_password_change_fails_with_mismatched_passwords",
        "test_password_change_redirect_custom",
        "test_password_change_redirect_custom_named",
        "test_password_change_redirect_default",
        "test_password_change_succeeds",
        "test_dates_query",
        "test_extra_stay_tied",
        "test_extra_values_distinct_ordering",
        "test_regression_10847",
        "test_regression_17877",
        "test_regression_7314_7372",
        "test_regression_7957",
        "test_regression_7961",
        "test_regression_8039",
        "test_regression_8063",
        "test_regression_8819",
        "test_values_with_extra",
        "test_user_password_change_updates_session",
        "test_add_efficiency",
        "test_assign_clear_related_set",
        "test_assign_with_queryset",
        "test_clear_efficiency",
        "test_created_via_related_set",
        "test_created_without_related",
        "test_get_related",
        "test_related_null_to_field",
        "test_related_set",
        "test_remove_from_wrong_set",
        "test_set",
        "test_set_clear_non_bulk",
        "test_confirm_valid_custom_user",
        "test_model_form_clean_applies_to_model",
        "test_override_clean",
        "test_model_form_applies_localize_to_all_fields",
        "test_model_form_applies_localize_to_some_fields",
        "test_model_form_refuses_arbitrary_string",
        "test_get_pass",
        "test_get_pass_no_input",
        "test_nonexistent_username",
        "test_password_validation",
        "test_system_username",
        "test_that_changepassword_command_changes_joes_password",
        "test_that_changepassword_command_works_with_nonascii_output",
        "test_that_max_tries_exits_1",
        "test_cache_key_i18n_formatting",
        "test_cache_key_i18n_timezone",
        "test_cache_key_i18n_translation",
        "test_cache_key_i18n_translation_accept_language",
        "test_cache_key_no_i18n",
        "test_middleware",
        "test_middleware_doesnt_cache_streaming_response",
        "test_many_to_many",
        "test_callable_called_each_time_form_is_instantiated",
        "test_custom_field_with_queryset_but_no_limit_choices_to",
        "test_fields_for_model_applies_limit_choices_to",
        "test_limit_choices_to_callable_for_fk_rel",
        "test_limit_choices_to_callable_for_m2m_rel",
        "test_setattr_raises_validation_error_field_specific",
        "test_setattr_raises_validation_error_non_field",
        "test_overridden_get_lookup",
        "test_overridden_get_lookup_chain",
        "test_overridden_get_transform",
        "test_overridden_get_transform_chain",
        "test_confirm_invalid_uuid",
        "test_confirm_valid_custom_user",
        "test_custom_implementation_year_exact",
        "test_postgres_year_exact",
        "test_year_lte_sql",
        "test_call_order",
        "test_custom_valid_name_callable_upload_to",
        "test_duplicate_filename",
        "test_empty_upload_to",
        "test_extended_length_storage",
        "test_file_object",
        "test_file_truncation",
        "test_filefield_default",
        "test_filefield_pickling",
        "test_filefield_read",
        "test_filefield_reopen",
        "test_filefield_write",
        "test_files",
        "test_random_upload_to",
        "test_stringio",
        "test_basics",
        "test_choice_iterator_passes_model_to_widget",
        "test_choices",
        "test_choices_bool",
        "test_choices_bool_empty_label",
        "test_choices_freshness",
        "test_choices_not_fetched_when_not_rendering",
        "test_deepcopies_widget",
        "test_disabled_modelchoicefield",
        "test_disabled_modelchoicefield_has_changed",
        "test_disabled_modelmultiplechoicefield_has_changed",
        "test_disabled_multiplemodelchoicefield",
        "test_no_extra_query_when_accessing_attrs",
        "test_num_queries",
        "test_overridable_choice_iterator",
        "test_queryset_manager",
        "test_queryset_none",
        "test_result_cache_not_shared",
        "test_lazy",
        "test_safestr",
        "test_verbose_name",
        "test_subquery_usage",
        "test_chained_values_with_expression",
        "test_values_expression",
        "test_values_expression_group_by",
        "test_values_list_expression",
        "test_values_list_expression_flat",
        "test_current_site_in_context_after_login",
        "test_login_csrf_rotate",
        "test_login_form_contains_request",
        "test_login_session_without_hash_session_key",
        "test_security_check",
        "test_security_check_https",
        "test_session_key_flushed_on_login",
        "test_session_key_flushed_on_login_after_password_change",
        "test_bilateral_fexpr",
        "test_bilateral_inner_qs",
        "test_bilateral_multi_value",
        "test_bilateral_order",
        "test_bilateral_upper",
        "test_div3_bilateral_extract",
        "test_transform_order_by",
        "test_empty",
        "test_callable_field_default",
        "test_choices_type",
        "test_foreignkeys_which_use_to_field",
        "test_iterable_model_m2m",
        "test_media_on_modelform",
        "test_model_field_that_returns_none_to_exclude_itself_with_explicit_fields",
        "test_prefetch_related_queryset",
        "test_update",
        "test_update_all",
        "test_update_annotated_multi_table_queryset",
        "test_update_annotated_queryset",
        "test_update_fk",
        "test_update_m2m_field",
        "test_update_multiple_fields",
        "test_update_multiple_objects",
        "test_update_respects_to_field",
        "test_update_slice_fail",
        "test_month_aggregation",
        "test_multiple_transforms_in_values",
        "test_transform_in_values",
        "test_F_reuse",
        "test_insensitive_patterns_escape",
        "test_patterns_escape",
        "test_deconstruct",
        "test_deconstruct_output_field",
        "test_equal",
        "test_equal_output_field",
        "test_hash",
        "test_raise_empty_expressionlist",
        "test_update_TimeField_using_Value",
        "test_update_UUIDField_using_Value",
        "test_basic_lookup",
        "test_custom_exact_lookup_none_rhs",
        "test_custom_name_lookup",
        "test_div3_extract",
        "test_foreignobject_lookup_registration",
        "test_lookups_caching",
        "test_language_not_saved_to_session",
        "test_streaming_response",
        "test_assignment_of_none",
        "test_assignment_of_none_null_false",
        "test_modelform_onetoonefield",
        "test_modelform_subclassed_model",
        "test_onetoonefield",
        "test_complex_expressions",
        "test_fill_with_value_from_same_object",
        "test_filter_not_equals_other_field",
        "test_incorrect_field_expression",
        "test_increment_value",
        "test_complex_expressions_do_not_introduce_sql_injection_via_untrusted_string_inclusion",
        "test_expressions_in_lookups_join_choice",
        "test_in_lookup_allows_F_expressions_and_expressions_for_datetimes",
        "test_in_lookup_allows_F_expressions_and_expressions_for_integers",
        "test_range_lookup_allows_F_expressions_and_expressions_for_integers",
        "test_article_form",
        "test_bad_form",
        "test_base_form",
        "test_blank_false_with_null_true_foreign_key_field",
        "test_blank_with_null_foreign_key_field",
        "test_confused_form",
        "test_default_filefield",
        "test_default_not_populated_on_checkboxselectmultiple",
        "test_default_not_populated_on_optional_checkbox_input",
        "test_default_not_populated_on_selectmultiple",
        "test_default_populated_on_optional_field",
        "test_default_selectdatewidget",
        "test_default_splitdatetime_field",
        "test_empty_fields_on_modelform",
        "test_empty_fields_to_construct_instance",
        "test_empty_fields_to_fields_for_model",
        "test_exclude_and_validation",
        "test_exclude_fields",
        "test_exclude_fields_with_string",
        "test_exclude_nonexistent_field",
        "test_extra_declared_field_model_form",
        "test_extra_field_model_form",
        "test_extra_field_modelform_factory",
        "test_extra_fields",
        "test_invalid_meta_model",
        "test_limit_fields_with_string",
        "test_limit_nonexistent_field",
        "test_missing_fields_attribute",
        "test_mixmodel_form",
        "test_no_model_class",
        "test_orderfields2_form",
        "test_orderfields_form",
        "test_override_field",
        "test_prefixed_form_with_default_field",
        "test_renderer_kwarg",
        "test_replace_field",
        "test_replace_field_variant_2",
        "test_replace_field_variant_3",
        "test_save_blank_false_with_required_false",
        "test_save_blank_null_unique_charfield_saves_null",
        "test_subcategory_form",
        "test_subclassmeta_form",
        "test_aggregates",
        "test_expressions",
        "test_filtered_aggregates",
        "test_functions",
        "test_abstract_inherited_unique",
        "test_abstract_inherited_unique_together",
        "test_explicitpk_unique",
        "test_explicitpk_unspecified",
        "test_inherited_unique",
        "test_inherited_unique_for_date",
        "test_inherited_unique_together",
        "test_multiple_field_unique_together",
        "test_override_unique_for_date_message",
        "test_override_unique_message",
        "test_override_unique_together_message",
        "test_simple_unique",
        "test_unique_for_date",
        "test_unique_for_date_in_exclude",
        "test_unique_for_date_with_nullable_date",
        "test_unique_null",
        "test_unique_together",
        "test_lefthand_addition",
        "test_lefthand_bitwise_and",
        "test_lefthand_bitwise_left_shift_operator",
        "test_lefthand_bitwise_or",
        "test_lefthand_bitwise_right_shift_operator",
        "test_lefthand_division",
        "test_lefthand_modulo",
        "test_lefthand_multiplication",
        "test_lefthand_power",
        "test_lefthand_subtraction",
        "test_right_hand_addition",
        "test_right_hand_division",
        "test_right_hand_modulo",
        "test_right_hand_multiplication",
        "test_right_hand_subtraction",
        "test_righthand_power",
        "test_empty_update",
        "test_empty_update_with_inheritance",
        "test_foreign_key_update_with_id",
        "test_nonempty_update",
        "test_nonempty_update_with_inheritance",
        "test_default",
        "test_guest",
        "test_permission_required_logged_in",
        "test_permission_required_not_logged_in",
        "test_redirect",
        "test_redirect_loop",
        "test_redirect_param",
        "test_redirect_url",
        "test_auto_id",
        "test_base_form",
        "test_basic_creation",
        "test_custom_form_fields",
        "test_initial_values",
        "test_m2m_editing",
        "test_m2m_initial_callable",
        "test_multi_fields",
        "test_recleaning_model_form_instance",
        "test_runtime_choicefield_populated",
        "test_save_commit_false",
        "test_save_with_data_errors",
        "test_subset_fields",
        "test_clean_does_deduplicate_values",
        "test_model_multiple_choice_field",
        "test_model_multiple_choice_field_22745",
        "test_model_multiple_choice_number_of_queries",
        "test_model_multiple_choice_required_false",
        "test_model_multiple_choice_run_validators",
        "test_model_multiple_choice_show_hidden_initial",
        "test_show_hidden_initial_changed_queries_efficiently",
        "test_to_field_name_with_initial_data",
        "test_force_update",
        "test_force_update_on_inherited_model",
        "test_force_update_on_inherited_model_without_fields",
        "test_force_update_on_proxy_model",
        "test_add_form_deletion_when_invalid",
        "test_change_form_deletion_when_invalid",
        "test_deletion",
        "test_save_new",
        "test_any_iterable_allowed_as_argument_to_exclude",
        "test_exception_on_unspecified_foreign_key",
        "test_fk_in_all_formset_forms",
        "test_fk_name_not_foreign_key_field_from_child",
        "test_fk_not_duplicated_in_form_fields",
        "test_inline_formset_factory",
        "test_non_foreign_key_field",
        "test_unsaved_fk_validate_unique",
        "test_zero_primary_key",
        "test_getter",
        "test_setter",
        "test_add_domain",
        "test_atom_feed",
        "test_atom_feed_published_and_updated_elements",
        "test_atom_multiple_enclosures",
        "test_atom_single_enclosure",
        "test_aware_datetime_conversion",
        "test_custom_feed_generator",
        "test_feed_last_modified_time",
        "test_feed_last_modified_time_naive_date",
        "test_feed_url",
        "test_item_link_error",
        "test_latest_post_date",
        "test_naive_datetime_conversion",
        "test_rss091_feed",
        "test_rss2_feed",
        "test_rss2_feed_guid_permalink_false",
        "test_rss2_feed_guid_permalink_true",
        "test_rss2_multiple_enclosures",
        "test_rss2_single_enclosure",
        "test_secure_urls",
        "test_title_escaping"
    ],
    "django__django-10554": [
        "test_union_with_values_list_and_order",
        "test_union_with_values_list_on_annotated_and_unannotated"
    ],
    "django__django-10880": [
        "test_count_distinct_expression"
    ],
    "django__django-10914": [
        "test_override_file_upload_permissions"
    ],
    "django__django-10973": [
        "test_accent",
        "test_basic",
        "test_column",
        "test_nopass",
        "test_sigint_handler"
    ],
    "django__django-10999": [
        "test_negative",
        "test_parse_postgresql_format"
    ],
    "django__django-11066": [
        "test_existing_content_type_rename_other_database"
    ],
    "django__django-11087": [
        "test_only_referenced_fields_selected"
    ],
    "django__django-11095": [
        "test_get_inline_instances_override_get_inlines"
    ],
    "django__django-11099": [
        "test_ascii_validator",
        "test_unicode_validator",
        "test_help_text"
    ],
    "django__django-11119": [
        "test_autoescape_off"
    ],
    "django__django-11133": [
        "test_memoryview_content"
    ],
    "django__django-11138": [
        "test_query_convert_timezones"
    ],
    "django__django-11141": [
        "test_loading_namespace_package"
    ],
    "django__django-11149": [
        "test_inline_add_m2m_view_only_perm",
        "test_inline_change_m2m_view_only_perm"
    ],
    "django__django-11163": [
        "test_modelform_subclassed_model"
    ],
    "django__django-11179": [
        "test_fast_delete_instance_set_pk_none"
    ],
    "django__django-11206": [
        "test_decimal_numbers",
        "test_decimal_subclass"
    ],
    "django__django-11211": [
        "test_prefetch_GFK_uuid_pk"
    ],
    "django__django-11239": [
        "test_ssl_certificate"
    ],
    "django__django-11265": [
        "test_with_exclude"
    ],
    "django__django-11276": [
        "test_make_list02",
        "test_password_help_text",
        "test_url_split_chars",
        "test_wrapping_characters",
        "test_addslashes02",
        "test_title1",
        "test_urlize01",
        "test_urlize06",
        "test_html_escaped",
        "test_url12",
        "test_initial_values",
        "test_m2m_initial_callable",
        "test_multi_fields",
        "test_runtime_choicefield_populated",
        "test_no_referer",
        "test_escape",
        "test_escapejs",
        "test_escaping",
        "test_templates_with_forms",
        "test_no_request",
        "test_request_and_exception",
        "test_request_and_message",
        "test_methods_with_arguments_display_arguments_default_value",
        "test_local_variable_escaping",
        "test_message_only",
        "test_request_with_items_key"
    ],
    "django__django-11292": [
        "test_skip_checks"
    ],
    "django__django-11299": [
        "test_simplecol_query"
    ],
    "django__django-11333": [
        "test_resolver_cache_default__root_urlconf"
    ],
    "django__django-11400": [
        "test_get_choices_default_ordering",
        "test_get_choices_reverse_related_field_default_ordering",
        "test_relatedfieldlistfilter_foreignkey_default_ordering",
        "test_relatedfieldlistfilter_reverse_relationships_default_ordering",
        "test_relatedonlyfieldlistfilter_foreignkey_default_ordering",
        "test_relatedonlyfieldlistfilter_foreignkey_ordering"
    ],
    "django__django-11433": [
        "test_default_not_populated_on_non_empty_value_in_cleaned_data"
    ],
    "django__django-11451": [
        "test_authentication_without_credentials",
        "test_custom_perms",
        "test_authentication_without_credentials",
        "test_custom_perms",
        "test_authentication_without_credentials",
        "test_custom_perms"
    ],
    "django__django-11477": [
        "test_re_path_with_optional_parameter",
        "test_two_variable_at_start_of_path_pattern",
        "test_translate_url_utility"
    ],
    "django__django-11490": [
        "test_union_with_values"
    ],
    "django__django-11532": [
        "test_non_ascii_dns_non_unicode_email"
    ],
    "django__django-11551": [
        "test_valid_field_accessible_via_instance"
    ],
    "django__django-11555": [
        "test_order_by_ptr_field_with_default_ordering_by_expression"
    ],
    "django__django-11603": [
        "test_distinct_on_aggregate",
        "test_empty_aggregate"
    ],
    "django__django-11728": [
        "test_simplify_regex",
        "test_app_not_found"
    ],
    "django__django-11734": [
        "test_subquery_exclude_outerref"
    ],
    "django__django-11740": [
        "test_alter_field_to_fk_dependency_other_app"
    ],
    "django__django-11749": [
        "test_mutually_exclusive_group_required_options"
    ],
    "django__django-11790": [
        "test_username_field_max_length_defaults_to_254",
        "test_username_field_max_length_matches_user_model"
    ],
    "django__django-11815": [
        "test_serialize_class_based_validators",
        "test_serialize_enums"
    ],
    "django__django-11820": [
        "test_ordering_pointing_multiple_times_to_model_fields",
        "test_ordering_pointing_to_related_model_pk"
    ],
    "django__django-11848": [
        "test_parsing_rfc850",
        "test_parsing_year_less_than_70"
    ],
    "django__django-11880": [
        "test_field_deep_copy_error_messages"
    ],
    "django__django-11885": [
        "test_fast_delete_combined_relationships"
    ],
    "django__django-11951": [
        "test_explicit_batch_size_respects_max_batch_size"
    ],
    "django__django-11964": [
        "test_str",
        "test_textchoices"
    ],
    "django__django-11999": [
        "test_overriding_FIELD_display"
    ],
    "django__django-12039": [
        "test_descending_columns_list_sql"
    ],
    "django__django-12050": [
        "test_iterable_lookup_value"
    ],
    "django__django-12125": [
        "test_serialize_nested_class",
        "test_serialize_numbers"
    ],
    "django__django-12143": [
        "test_get_list_editable_queryset_with_regex_chars_in_prefix"
    ],
    "django__django-12155": [
        "test_parse_rst_with_docstring_no_leading_line_feed"
    ],
    "django__django-12193": [
        "test_get_context_does_not_mutate_attrs"
    ],
    "django__django-12209": [
        "test_json_serializer",
        "test_python_serializer",
        "test_xml_serializer",
        "test_yaml_serializer"
    ],
    "django__django-12262": [
        "test_inclusion_tag_errors",
        "test_inclusion_tags",
        "test_simple_tag_errors",
        "test_simple_tags"
    ],
    "django__django-12273": [
        "test_create_new_instance_with_pk_equals_none",
        "test_create_new_instance_with_pk_equals_none_multi_inheritance"
    ],
    "django__django-12276": [
        "test_use_required_attribute",
        "test_filefield_with_fileinput_required"
    ],
    "django__django-12304": [
        "test_templates"
    ],
    "django__django-12308": [
        "test_json_display_for_field",
        "test_label_for_field"
    ],
    "django__django-12325": [
        "test_clash_parent_link",
        "test_onetoone_with_parent_model"
    ],
    "django__django-12406": [
        "test_non_blank_foreign_key_with_radio",
        "test_choices_radio_blank",
        "test_clean_model_instance"
    ],
    "django__django-12419": [
        "test_middleware_headers"
    ],
    "django__django-12663": [
        "test_subquery_filter_by_lazy"
    ],
    "django__django-12708": [
        "test_alter_index_together_remove_with_unique_together"
    ],
    "django__django-12713": [
        "test_formfield_overrides_m2m_filter_widget"
    ],
    "django__django-12741": [
        "test_execute_sql_flush_statements",
        "test_sequence_name_length_limits_flush"
    ],
    "django__django-12754": [
        "test_add_model_with_field_removed_from_base_model"
    ],
    "django__django-12774": [
        "test_in_bulk_meta_constraint"
    ],
    "django__django-12858": [
        "test_ordering_pointing_to_lookup_not_transform"
    ],
    "django__django-12965": [
        "test_fast_delete_all"
    ],
    "django__django-13012": [
        "test_empty_group_by",
        "test_non_empty_group_by"
    ],
    "django__django-13023": [
        "test_invalid_value",
        "test_lookup_really_big_value"
    ],
    "django__django-13028": [
        "test_field_with_filterable",
        "test_ticket8439"
    ],
    "django__django-13033": [
        "test_order_by_self_referential_fk"
    ],
    "django__django-13089": [
        "test_cull_delete_when_store_empty",
        "test_cull_delete_when_store_empty"
    ],
    "django__django-13109": [
        "test_FK_validates_using_base_manager",
        "test_validate_foreign_key_to_model_with_overridden_manager"
    ],
    "django__django-13112": [
        "test_reference_mixed_case_app_label"
    ],
    "django__django-13121": [
        "test_duration_expressions"
    ],
    "django__django-13128": [
        "test_date_case_subtraction",
        "test_date_subquery_subtraction",
        "test_date_subtraction",
        "test_datetime_subquery_subtraction",
        "test_datetime_subtraction_microseconds",
        "test_time_subquery_subtraction",
        "test_time_subtraction"
    ],
    "django__django-13158": [
        "test_union_none"
    ],
    "django__django-13195": [
        "test_delete_cookie_samesite",
        "test_delete_cookie_secure_samesite_none",
        "test_session_delete_on_end",
        "test_session_delete_on_end_with_custom_domain_and_path",
        "test_cookie_setings"
    ],
    "django__django-13212": [
        "test_value_placeholder_with_char_field",
        "test_value_placeholder_with_decimal_field",
        "test_value_placeholder_with_file_field",
        "test_value_placeholder_with_integer_field",
        "test_value_placeholder_with_null_character"
    ],
    "django__django-13279": [
        "test_default_hashing_algorith_legacy_decode",
        "test_default_hashing_algorith_legacy_decode",
        "test_default_hashing_algorith_legacy_decode",
        "test_default_hashing_algorith_legacy_decode",
        "test_default_hashing_algorith_legacy_decode",
        "test_default_hashing_algorith_legacy_decode",
        "test_default_hashing_algorith_legacy_decode",
        "test_default_hashing_algorith_legacy_decode",
        "test_default_hashing_algorith_legacy_decode"
    ],
    "django__django-13297": [
        "test_template_params_filtering"
    ],
    "django__django-13315": [
        "test_limit_choices_to_no_duplicates"
    ],
    "django__django-13343": [
        "test_deconstruction"
    ],
    "django__django-13344": [
        "test_coroutine",
        "test_deprecation"
    ],
    "django__django-13346": [
        "test_key_in",
        "test_key_iregex"
    ],
    "django__django-13363": [
        "test_trunc_timezone_applied_before_truncation"
    ],
    "django__django-13401": [
        "test_abstract_inherited_fields"
    ],
    "django__django-13406": [
        "test_annotation_values",
        "test_annotation_values_list",
        "test_annotation_with_callable_default"
    ],
    "django__django-13410": [
        "test_exclusive_lock",
        "test_shared_lock"
    ],
    "django__django-13417": [
        "test_annotated_default_ordering",
        "test_annotated_values_default_ordering"
    ],
    "django__django-13449": [
        "test_lag_decimalfield"
    ],
    "django__django-13512": [
        "test_prepare_value",
        "test_json_display_for_field",
        "test_label_for_field"
    ],
    "django__django-13513": [
        "test_innermost_exception_without_traceback"
    ],
    "django__django-13516": [
        "test_outputwrapper_flush"
    ],
    "django__django-13551": [
        "test_token_with_different_email",
        "test_token_with_different_secret"
    ],
    "django__django-13568": [
        "test_username_unique_with_model_constraint"
    ],
    "django__django-13569": [
        "test_aggregation_random_ordering"
    ],
    "django__django-13590": [
        "test_range_lookup_namedtuple"
    ],
    "django__django-13658": [
        "test_program_name_from_argv"
    ],
    "django__django-13670": [
        "test_year_before_1000"
    ],
    "django__django-13741": [
        "test_readonly_field_has_changed"
    ],
    "django__django-13786": [
        "test_create_model_and_remove_model_options"
    ],
    "django__django-13794": [
        "test_lazy_add",
        "test_add08",
        "test_add09"
    ],
    "django__django-13807": [
        "test_check_constraints_sql_keywords"
    ],
    "django__django-13809": [
        "test_skip_checks"
    ],
    "django__django-13810": [
        "test_async_and_sync_middleware_chain_async_call"
    ],
    "django__django-13820": [
        "test_loading_package_without__file__"
    ],
    "django__django-13821": [
        "test_check_sqlite_version"
    ],
    "django__django-13837": [
        "test_run_as_non_django_module"
    ],
    "django__django-13925": [
        "test_auto_created_inherited_pk",
        "test_explicit_inherited_pk"
    ],
    "django__django-13933": [
        "test_modelchoicefield_value_placeholder"
    ],
    "django__django-13964": [
        "test_save_fk_after_parent_with_non_numeric_pk_set_on_child"
    ],
    "django__django-14007": [
        "test_auto_field_subclass_create"
    ],
    "django__django-14011": [
        "test_live_server_url_is_class_property",
        "test_database_writes",
        "test_fixtures_loaded",
        "test_check_model_instance_from_subview",
        "test_view_calls_subview",
        "test_404",
        "test_closes_connection_without_content_length",
        "test_environ",
        "test_keep_alive_connection_clears_previous_request_data",
        "test_keep_alive_on_connection_with_content_length",
        "test_media_files",
        "test_no_collectstatic_emulation",
        "test_protocol",
        "test_static_files",
        "test_view",
        "test_port_bind",
        "test_specified_port_bind"
    ],
    "django__django-14017": [
        "test_boolean_expression_combined",
        "test_boolean_expression_combined_with_empty_Q"
    ],
    "django__django-14034": [
        "test_render_required_attributes"
    ],
    "django__django-14053": [
        "test_post_processing"
    ],
    "django__django-14089": [
        "test_reversed"
    ],
    "django__django-14122": [
        "test_default_ordering_does_not_affect_group_by"
    ],
    "django__django-14140": [
        "test_deconstruct",
        "test_deconstruct_boolean_expression",
        "test_deconstruct_negated",
        "test_boolean_expression_combined_with_empty_Q"
    ],
    "django__django-14155": [
        "test_repr",
        "test_repr_functools_partial",
        "test_resolver_match_on_request"
    ],
    "django__django-14170": [
        "test_extract_iso_year_func_boundaries",
        "test_extract_iso_year_func_boundaries"
    ],
    "django__django-14238": [
        "test_issubclass_of_autofield",
        "test_default_auto_field_setting_bigautofield_subclass"
    ],
    "django__django-14311": [
        "test_run_as_non_django_module_non_package"
    ],
    "django__django-14315": [
        "test_runshell_use_environ",
        "test_settings_to_cmd_args_env",
        "test_accent",
        "test_basic",
        "test_column",
        "test_crash_password_does_not_leak",
        "test_nopass",
        "test_parameters",
        "test_passfile",
        "test_service",
        "test_ssl_certificate"
    ],
    "django__django-14349": [
        "test_validators"
    ],
    "django__django-14351": [
        "test_having_subquery_select"
    ],
    "django__django-14373": [
        "test_Y_format_year_before_1000"
    ],
    "django__django-14376": [
        "test_options_non_deprecated_keys_preferred",
        "test_options_override_settings_proper_values",
        "test_parameters"
    ],
    "django__django-14404": [
        "test_missing_slash_append_slash_true_force_script_name",
        "test_missing_slash_append_slash_true_script_name"
    ],
    "django__django-14434": [
        "test_unique_constraint"
    ],
    "django__django-14493": [
        "test_collectstatistic_no_post_process_replaced_paths"
    ],
    "django__django-14500": [
        "test_migrate_marks_replacement_unapplied"
    ],
    "django__django-14534": [
        "test_boundfield_subwidget_id_for_label",
        "test_iterable_boundfield_select"
    ],
    "django__django-14539": [
        "test_urlize",
        "test_urlize_unchanged_inputs"
    ],
    "django__django-14559": [
        "test_empty_objects",
        "test_large_batch",
        "test_updated_rows_when_passing_duplicates"
    ],
    "django__django-14580": [
        "test_serialize_type_model"
    ],
    "django__django-14608": [
        "test_formset_validate_max_flag",
        "test_formset_validate_min_flag",
        "test_non_form_errors",
        "test_non_form_errors_is_errorlist"
    ],
    "django__django-14631": [
        "test_datetime_clean_disabled_callable_initial_bound_field",
        "test_datetime_clean_disabled_callable_initial_microseconds"
    ],
    "django__django-14672": [
        "test_multiple_autofields",
        "test_db_column_clash",
        "test_ending_with_underscore",
        "test_including_separator",
        "test_pk",
        "test_check_jsonfield",
        "test_check_jsonfield_required_db_features",
        "test_ordering_pointing_to_json_field_value",
        "test_choices",
        "test_retrieval",
        "test_list_containing_non_iterable",
        "test_non_iterable",
        "test_non_list",
        "test_pointing_to_fk",
        "test_pointing_to_m2m",
        "test_pointing_to_missing_field",
        "test_valid_model",
        "test_list_containing_non_iterable",
        "test_non_iterable",
        "test_non_list",
        "test_pointing_to_fk",
        "test_pointing_to_m2m_field",
        "test_pointing_to_missing_field",
        "test_pointing_to_non_local_field",
        "test_field_name_clash_with_child_accessor",
        "test_field_name_clash_with_m2m_through",
        "test_id_clash",
        "test_inheritance_clash",
        "test_multigeneration_inheritance",
        "test_multiinheritance_clash",
        "test_func_index",
        "test_func_index_complex_expression_custom_lookup",
        "test_func_index_pointing_to_fk",
        "test_func_index_pointing_to_m2m_field",
        "test_func_index_pointing_to_missing_field",
        "test_func_index_pointing_to_missing_field_nested",
        "test_func_index_pointing_to_non_local_field",
        "test_func_index_required_db_features",
        "test_index_with_condition",
        "test_index_with_condition_required_db_features",
        "test_index_with_include",
        "test_index_with_include_required_db_features",
        "test_max_name_length",
        "test_name_constraints",
        "test_pointing_to_fk",
        "test_pointing_to_m2m_field",
        "test_pointing_to_missing_field",
        "test_pointing_to_non_local_field",
        "test_add_on_symmetrical_m2m_with_intermediate_model",
        "test_self_referential_empty_qs",
        "test_self_referential_non_symmetrical_both",
        "test_self_referential_non_symmetrical_clear_first_side",
        "test_self_referential_non_symmetrical_first_side",
        "test_self_referential_non_symmetrical_second_side",
        "test_self_referential_symmetrical",
        "test_set_on_symmetrical_m2m_with_intermediate_model",
        "test_through_fields_self_referential",
        "test_just_order_with_respect_to_no_errors",
        "test_just_ordering_no_errors",
        "test_lazy_reference_checks",
        "test_m2m_autogenerated_table_name_clash",
        "test_m2m_autogenerated_table_name_clash_database_routers_installed",
        "test_m2m_field_table_name_clash",
        "test_m2m_field_table_name_clash_database_routers_installed",
        "test_m2m_table_name_clash",
        "test_m2m_table_name_clash_database_routers_installed",
        "test_m2m_to_concrete_and_proxy_allowed",
        "test_m2m_unmanaged_shadow_models_not_checked",
        "test_name_beginning_with_underscore",
        "test_name_contains_double_underscores",
        "test_name_ending_with_underscore",
        "test_non_valid",
        "test_onetoone_with_explicit_parent_link_parent_model",
        "test_onetoone_with_parent_model",
        "test_ordering_allows_registered_lookups",
        "test_ordering_non_iterable",
        "test_ordering_pointing_multiple_times_to_model_fields",
        "test_ordering_pointing_to_foreignkey_field",
        "test_ordering_pointing_to_lookup_not_transform",
        "test_ordering_pointing_to_missing_field",
        "test_ordering_pointing_to_missing_foreignkey_field",
        "test_ordering_pointing_to_missing_related_field",
        "test_ordering_pointing_to_missing_related_model_field",
        "test_ordering_pointing_to_non_related_field",
        "test_ordering_pointing_to_related_model_pk",
        "test_ordering_pointing_to_two_related_model_field",
        "test_ordering_with_order_with_respect_to",
        "test_property_and_related_field_accessor_clash",
        "test_single_primary_key",
        "test_swappable_missing_app",
        "test_swappable_missing_app_name",
        "test_two_m2m_through_same_model_with_different_through_fields",
        "test_two_m2m_through_same_relationship",
        "test_unique_primary_key",
        "test_check_constraint_pointing_to_fk",
        "test_check_constraint_pointing_to_joined_fields",
        "test_check_constraint_pointing_to_joined_fields_complex_check",
        "test_check_constraint_pointing_to_m2m_field",
        "test_check_constraint_pointing_to_missing_field",
        "test_check_constraint_pointing_to_non_local_field",
        "test_check_constraint_pointing_to_pk",
        "test_check_constraint_pointing_to_reverse_fk",
        "test_check_constraint_pointing_to_reverse_o2o",
        "test_check_constraints",
        "test_check_constraints_required_db_features",
        "test_deferrable_unique_constraint",
        "test_deferrable_unique_constraint_required_db_features",
        "test_func_unique_constraint",
        "test_func_unique_constraint_expression_custom_lookup",
        "test_func_unique_constraint_pointing_to_fk",
        "test_func_unique_constraint_pointing_to_m2m_field",
        "test_func_unique_constraint_pointing_to_missing_field",
        "test_func_unique_constraint_pointing_to_missing_field_nested",
        "test_func_unique_constraint_pointing_to_non_local_field",
        "test_func_unique_constraint_required_db_features",
        "test_unique_constraint_condition_pointing_to_joined_fields",
        "test_unique_constraint_condition_pointing_to_missing_field",
        "test_unique_constraint_pointing_to_fk",
        "test_unique_constraint_pointing_to_m2m_field",
        "test_unique_constraint_pointing_to_missing_field",
        "test_unique_constraint_pointing_to_non_local_field",
        "test_unique_constraint_pointing_to_reverse_o2o",
        "test_unique_constraint_with_condition",
        "test_unique_constraint_with_condition_required_db_features",
        "test_unique_constraint_with_include",
        "test_unique_constraint_with_include_required_db_features",
        "test_add_on_m2m_with_intermediate_model",
        "test_add_on_m2m_with_intermediate_model_callable_through_default",
        "test_add_on_m2m_with_intermediate_model_value_required",
        "test_add_on_m2m_with_intermediate_model_value_required_fails",
        "test_add_on_reverse_m2m_with_intermediate_model",
        "test_clear_on_reverse_removes_all_the_m2m_relationships",
        "test_clear_removes_all_the_m2m_relationships",
        "test_create_on_m2m_with_intermediate_model",
        "test_create_on_m2m_with_intermediate_model_callable_through_default",
        "test_create_on_m2m_with_intermediate_model_value_required",
        "test_create_on_m2m_with_intermediate_model_value_required_fails",
        "test_create_on_reverse_m2m_with_intermediate_model",
        "test_custom_related_name_doesnt_conflict_with_fky_related_name",
        "test_custom_related_name_forward_empty_qs",
        "test_custom_related_name_forward_non_empty_qs",
        "test_custom_related_name_reverse_empty_qs",
        "test_custom_related_name_reverse_non_empty_qs",
        "test_filter_on_intermediate_model",
        "test_get_on_intermediate_model",
        "test_get_or_create_on_m2m_with_intermediate_model_value_required",
        "test_get_or_create_on_m2m_with_intermediate_model_value_required_fails",
        "test_order_by_relational_field_through_model",
        "test_query_first_model_by_intermediate_model_attribute",
        "test_query_model_by_attribute_name_of_related_model",
        "test_query_model_by_custom_related_name",
        "test_query_model_by_intermediate_can_return_non_unique_queryset",
        "test_query_model_by_related_model_name",
        "test_query_second_model_by_intermediate_model_attribute",
        "test_remove_on_m2m_with_intermediate_model",
        "test_remove_on_m2m_with_intermediate_model_multiple",
        "test_remove_on_reverse_m2m_with_intermediate_model",
        "test_retrieve_intermediate_items",
        "test_retrieve_reverse_intermediate_items",
        "test_reverse_inherited_m2m_with_through_fields_list_hashable",
        "test_set_on_m2m_with_intermediate_model",
        "test_set_on_m2m_with_intermediate_model_callable_through_default",
        "test_set_on_m2m_with_intermediate_model_value_required",
        "test_set_on_m2m_with_intermediate_model_value_required_fails",
        "test_set_on_reverse_m2m_with_intermediate_model",
        "test_through_fields",
        "test_update_or_create_on_m2m_with_intermediate_model_value_required",
        "test_update_or_create_on_m2m_with_intermediate_model_value_required_fails"
    ],
    "django__django-14725": [
        "test_edit_only",
        "test_edit_only_inlineformset_factory",
        "test_edit_only_object_outside_of_queryset"
    ],
    "django__django-14752": [
        "test_serialize_result"
    ],
    "django__django-14765": [
        "test_real_apps_non_set"
    ],
    "django__django-14771": [
        "test_xoptions"
    ],
    "django__django-14787": [
        "test_wrapper_assignments"
    ],
    "django__django-14792": [
        "test_get_timezone_name",
        "test_is_aware"
    ],
    "django__django-14855": [
        "test_readonly_foreignkey_links_custom_admin_site"
    ],
    "django__django-14915": [
        "test_choice_value_hash"
    ],
    "django__django-14999": [
        "test_rename_model_with_db_table_noop"
    ],
    "django__django-15022": [
        "test_many_search_terms",
        "test_multiple_search_fields",
        "test_related_field_multiple_search_terms"
    ],
    "django__django-15037": [
        "test_foreign_key_to_field"
    ],
    "django__django-15098": [
        "test_get_language_from_path_real",
        "test_get_supported_language_variant_null"
    ],
    "django__django-15103": [
        "test_without_id",
        "test_json_script_without_id"
    ],
    "django__django-15104": [
        "test_add_custom_fk_with_hardcoded_to"
    ],
    "django__django-15127": [
        "test_override_settings_level_tags"
    ],
    "django__django-15128": [
        "test_conflicting_aliases_during_combine"
    ],
    "django__django-15161": [
        "test_deconstruct",
        "test_deconstruct_output_field",
        "test_serialize_complex_func_index"
    ],
    "django__django-15252": [
        "test_migrate_test_setting_false_ensure_schema",
        "test_migrate_skips_schema_creation"
    ],
    "django__django-15268": [
        "test_foo_together_ordering",
        "test_remove_field_and_foo_together",
        "test_rename_field_and_foo_together"
    ],
    "django__django-15277": [
        "test_output_field_does_not_create_broken_validators",
        "test_raise_empty_expressionlist"
    ],
    "django__django-15278": [
        "test_add_field_o2o_nullable"
    ],
    "django__django-15280": [
        "test_nested_prefetch_is_not_overwritten_by_related_object"
    ],
    "django__django-15315": [
        "test_hash_immutability"
    ],
    "django__django-15368": [
        "test_f_expression"
    ],
    "django__django-15375": [
        "test_aggregation_default_after_annotation"
    ],
    "django__django-15380": [
        "test_rename_field_with_renamed_model"
    ],
    "django__django-15382": [
        "test_negated_empty_exists"
    ],
    "django__django-15467": [
        "test_radio_fields_foreignkey_formfield_overrides_empty_label"
    ],
    "django__django-15499": [
        "test_create_alter_model_managers"
    ],
    "django__django-15503": [
        "test_has_key_number",
        "test_has_keys"
    ],
    "django__django-15525": [
        "test_natural_key_dependencies"
    ],
    "django__django-15554": [
        "test_multiple"
    ],
    "django__django-15561": [
        "test_alter_field_choices_noop"
    ],
    "django__django-15563": [
        "test_mti_update_grand_parent_through_child",
        "test_mti_update_parent_through_child"
    ],
    "django__django-15569": [
        "test_get_transforms",
        "test_lookups_caching"
    ],
    "django__django-15572": [
        "test_template_dirs_ignore_empty_path"
    ],
    "django__django-15629": [
        "test_alter_field_pk_fk_db_collation",
        "test_create_fk_models_to_pk_field_db_collation"
    ],
    "django__django-15695": [
        "test_rename_index_unnamed_index"
    ],
    "django__django-15731": [
        "test_manager_method_signature"
    ],
    "django__django-15732": [
        "test_remove_unique_together_on_unique_field"
    ],
    "django__django-15741": [
        "test_date_lazy",
        "test_get_format_lazy_format"
    ],
    "django__django-15814": [
        "test_select_related_only"
    ],
    "django__django-15851": [
        "test_parameters"
    ],
    "django__django-15863": [
        "test_inputs"
    ],
    "django__django-15916": [
        "test_custom_callback_from_base_form_meta",
        "test_custom_callback_in_meta"
    ],
    "django__django-15930": [
        "test_annotate_with_full_when"
    ],
    "django__django-15957": [
        "test_foreignkey_reverse",
        "test_m2m_forward",
        "test_m2m_reverse",
        "test_reverse_ordering"
    ],
    "django__django-15973": [
        "test_create_with_through_model_separate_apps"
    ],
    "django__django-15987": [
        "test_fixture_dirs_with_default_fixture_path_as_pathlib"
    ],
    "django__django-16032": [
        "test_annotation_and_alias_filter_in_subquery",
        "test_annotation_and_alias_filter_related_in_subquery"
    ],
    "django__django-16082": [
        "test_resolve_output_field_number",
        "test_resolve_output_field_with_null"
    ],
    "django__django-16100": [
        "test_list_editable_atomicity"
    ],
    "django__django-16116": [
        "test_makemigrations_check_with_changes"
    ],
    "django__django-16136": [
        "test_http_method_not_allowed_responds_correctly",
        "test_mixed_views_raise_error"
    ],
    "django__django-16139": [
        "test_link_to_password_reset_in_helptext_via_to_field"
    ],
    "django__django-16145": [
        "test_zero_ip_addr"
    ],
    "django__django-16255": [
        "test_callable_sitemod_no_items"
    ],
    "django__django-16256": [
        "test_acreate",
        "test_acreate_reverse",
        "test_aget_or_create",
        "test_aget_or_create_reverse",
        "test_aupdate_or_create",
        "test_aupdate_or_create_reverse",
        "test_generic_async_acreate",
        "test_generic_async_aget_or_create",
        "test_generic_async_aupdate_or_create"
    ],
    "django__django-16263": [
        "test_non_aggregate_annotation_pruned",
        "test_unreferenced_aggregate_annotation_pruned",
        "test_unused_aliased_aggregate_pruned"
    ],
    "django__django-16315": [
        "test_update_conflicts_unique_fields_update_fields_db_column"
    ],
    "django__django-16333": [
        "test_custom_form_saves_many_to_many_field"
    ],
    "django__django-16429": [
        "test_depth",
        "test_depth_invalid",
        "test_other_units",
        "test_thousand_years_ago"
    ],
    "django__django-16454": [
        "test_subparser_error_formatting"
    ],
    "django__django-16485": [
        "test_zero_values"
    ],
    "django__django-16493": [
        "test_deconstruction_storage_callable_default"
    ],
    "django__django-16502": [
        "test_no_body_returned_for_head_requests"
    ],
    "django__django-16527": [
        "test_submit_row_save_as_new_add_permission_required"
    ],
    "django__django-16560": [
        "test_custom_violation_code_message",
        "test_deconstruction",
        "test_eq",
        "test_repr_with_violation_error_code",
        "test_validate_custom_error",
        "test_eq",
        "test_repr_with_violation_error_code",
        "test_validate_conditon_custom_error"
    ],
    "django__django-16569": [
        "test_disable_delete_extra_formset_forms",
        "test_disable_delete_extra_formset_forms"
    ],
    "django__django-16595": [
        "test_alter_alter_field"
    ],
    "django__django-16612": [
        "test_missing_slash_append_slash_true_query_string",
        "test_missing_slash_append_slash_true_script_name_query_string"
    ],
    "django__django-16631": [
        "test_get_user_fallback_secret"
    ],
    "django__django-16642": [
        "test_compressed_response"
    ],
    "django__django-16661": [
        "test_lookup_allowed_foreign_primary"
    ],
    "django__django-16662": [
        "test_sorted_imports"
    ],
    "django__django-16667": [
        "test_form_field",
        "test_value_from_datadict"
    ],
    "django__django-16801": [
        "test_post_init_not_connected"
    ],
    "django__django-16819": [
        "test_add_remove_index"
    ],
    "django__django-16877": [
        "test_autoescape_off",
        "test_basic",
        "test_chain_join",
        "test_chain_join_autoescape_off"
    ],
    "django__django-16899": [
        "test_nonexistent_field",
        "test_nonexistent_field_on_inline"
    ],
    "django__django-16901": [
        "test_filter_multiple"
    ],
    "django__django-16938": [
        "test_altering_serialized_output",
        "test_deserialize_force_insert",
        "test_deterministic_mapping_ordering",
        "test_pre_1000ad_date",
        "test_serialize",
        "test_serialize_no_only_pk_with_natural_keys",
        "test_serialize_only_pk",
        "test_serialize_prefetch_related_m2m",
        "test_serialize_progressbar",
        "test_serializer_roundtrip",
        "test_serialize_no_only_pk_with_natural_keys",
        "test_serialize_only_pk",
        "test_serialize_prefetch_related_m2m",
        "test_serialize_progressbar",
        "test_serialize_no_only_pk_with_natural_keys",
        "test_serialize_only_pk",
        "test_serialize_prefetch_related_m2m",
        "test_serialize_progressbar",
        "test_control_char_failure",
        "test_serialize_no_only_pk_with_natural_keys",
        "test_serialize_only_pk",
        "test_serialize_prefetch_related_m2m",
        "test_serialize_progressbar"
    ],
    "django__django-16950": [
        "test_inlineformset_factory_nulls_default_pks_alternate_key_relation_data"
    ],
    "django__django-17029": [
        "test_clear_cache"
    ],
    "django__django-17084": [
        "test_referenced_window_requires_wrapping"
    ],
    "django__django-17087": [
        "test_serialize_nested_class_method"
    ],
    "django__django-7530": [
        "test_squashmigrations_initial_attribute"
    ],
    "django__django-9296": [
        "test_paginator_iteration"
    ]
}

# Designed for django__django-12209
# test functions are partial methods in a class
# we need to get the actual test method name as test id
PARTIAL_METHOD_NAMES = [
    "serializerTest",
]

def get_args(frame):
    arg_names = inspect.getargvalues(frame).args[1:]  # skip 'self'
    return [frame.f_locals.get(arg) for arg in arg_names]

def get_test_id(frame):
    _self = frame.f_locals.get("self", None)
    if _self is None:
        return frame.f_code.co_name
    for attr in dir(_self):
        _attr = getattr(_self, attr)
        if isinstance(_attr, partial):
            if _attr.func.__code__ == frame.f_code and list(_attr.args) == get_args(frame):
                return attr
    return frame.f_code.co_name

def _get_allowed_functions():
    value = os.getenv("TRACER_ALLOWED_FUNCTIONS", "")
    if not value:
        return set()
    assert isinstance(value, str)
    if value.strip().lower() == 'none':
        return set()
    return set(s.strip() for s in value.split(',') if s.strip())

ALLOWED_FUNCTIONS = _get_allowed_functions()

def _looks_like_unittest_func(frame):
    co = frame.f_code
    if co.co_name in PARTIAL_METHOD_NAMES:
        return get_test_id(frame)
    if not co.co_name.startswith("test_"):
        return None
    fn = (co.co_filename or "").replace("\\", "/")
    if "/tests/" in fn and fn.endswith(".py"):
        instance_id = os.getenv("INSTANCE_ID", "NA")
        fail_to_pass = FAIL_TO_PASS_TESTS.get(instance_id, [])
        if any(co.co_name == test_name for test_name in fail_to_pass):
            return co.co_name
    return None

def _profile_tracer(frame, event, arg):
    st = getattr(_state, "stack", None)
    if st is None:
        _state.stack = st = []
        _state.active = False
        _state.tid = None
        _state.tracer = None
    if event == "call":
        if not _state.active:
            tid = _looks_like_unittest_func(frame)
            if tid:
                _state.active = True
                _state.tid = tid
                output_file=os.path.join(os.environ.get('TRACER_OUTPUT_DIR'), "{}.jsonl".format(tid)) # type: ignore
                _state.tracer = ExecutionTracer(
                    output_file=output_file,
                    include_stdlib={"unittest"},
                    allowed_functions=ALLOWED_FUNCTIONS,
                )
                st.append("root")
                _state.tracer.start_tracing()
                _state.tracer._handle_call_event(frame, _state.tracer._get_function_info(frame))
                frame.f_trace = _state.tracer._trace_function
                return
        if _state.active:
            st.append("call")
    elif event == "return" and _state.active:
        if st:
            st.pop()
        if not st:
            _state.tracer.stop_tracing()
            try:
                _state.tracer.save_trace()
            except Exception as e:
                print("Failed to save trace to {}: {}".format(_state.tracer.output_file, e), file=sys.stderr, flush=True)
            _state.active = False
            _state.tid = None
            _state.tracer = None
        return

def _profile_inspector(frame, event, arg):
    st = getattr(_state, "stack", None)
    if st is None:
        _state.stack = st = []
        _state.active = False
        _state.tid = None
        _state.inspector = None
    if event == "call":
        if not _state.active:
            tid = _looks_like_unittest_func(frame)
            if tid:
                _state.active = True
                _state.tid = tid
                _state.inspector = ExpressionInspector(
                    bp_file=os.environ.get('INSPECTOR_BP_FILE'),
                    bp_line=int(os.environ.get('INSPECTOR_BP_LINE')),
                    expr=os.environ.get('INSPECTOR_EXPR'),
                    save_path=os.path.join(os.environ.get('INSPECTOR_OUTPUT_DIR'), "{}.jsonl".format(tid)),
                    count=int(os.environ.get('INSPECTOR_COUNT')),
                    mode=os.environ.get('INSPECTOR_MODE'),
                    bp_func_name=os.environ.get('INSPECTOR_BP_FUNC'),
                )
                st.append("root")
                _state.inspector.set_trace()
                return
        if _state.active:
            st.append("call")
    elif event == "return" and _state.active:
        if st:
            st.pop()
        if not st:
            _state.inspector.save_result()
            _state.active = False
            _state.tid = None
            _state.inspector = None
        return

def _profile_tracker(frame, event, arg):
    st = getattr(_state, "stack", None)
    if st is None:
        _state.stack = st = []
        _state.active = False
        _state.tid = None
        _state.tracer = None
    if event == "call":
        if not _state.active:
            tid = _looks_like_unittest_func(frame)
            if tid:
                _state.active = True
                _state.tid = tid
                output_file=os.path.join(os.environ.get('TRACER_OUTPUT_DIR'), "{}.jsonl".format(tid)) # type: ignore
                _state.tracer = Tracker(
                    output_file=output_file,
                    include_stdlib={"unittest"},
                    allowed_functions=ALLOWED_FUNCTIONS
                )
                st.append("root")
                _state.tracer.start_tracing()
                _state.tracer._handle_call_event(frame, _state.tracer._get_function_info(frame))
                frame.f_trace = _state.tracer._trace_function
                return
        if _state.active:
            st.append("call")
    elif event == "return" and _state.active:
        if st:
            st.pop()
        if not st:
            _state.tracer.stop_tracing()
            try:
                _state.tracer.save_trace()
            except Exception as e:
                print("Failed to save trace to {}: {}".format(_state.tracer.output_file, e), file=sys.stderr, flush=True)
            _state.active = False
            _state.tid = None
            _state.tracer = None
        return

def _install_tracer():
    sys.setprofile(_profile_tracer)
    try:
        threading.setprofile(_profile_tracer)
    except Exception:
        pass

def _install_inspector():
    sys.setprofile(_profile_inspector)
    try:
        threading.setprofile(_profile_inspector)
    except Exception:
        pass

def _install_tracker():
    sys.setprofile(_profile_tracker)
    try:
        threading.setprofile(_profile_tracker)
    except Exception:
        pass

if __name__ == "__main__":
    enable_tracer = os.environ.get("ENABLE_TRACER", "0") == "1"
    enable_inspector = os.environ.get("ENABLE_INSPECTOR", "0") == "1"
    enable_tracker = os.environ.get("ENABLE_TRACKER", "0") == "1"
    if enable_tracer + enable_inspector + enable_tracker > 1:
        raise RuntimeError("Cannot enable more than one of tracer, inspector, and tracker")
    if enable_tracer:
        _install_tracer()
    elif enable_inspector:
        _install_inspector()
    elif enable_tracker:
        _install_tracker()
