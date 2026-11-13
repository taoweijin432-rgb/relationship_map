WITH
relation_sample AS (
  SELECT id, parent_company_id, child_company_id, relation_type, verification_status,
         valid_from, valid_to
  FROM public.company_relation ORDER BY id LIMIT 3
),
company_keys AS (
  SELECT id FROM (SELECT id FROM public.company_standard
    WHERE verification_status = '已核验' ORDER BY id LIMIT 12) s
  UNION SELECT parent_company_id FROM relation_sample
  UNION SELECT child_company_id FROM relation_sample
),
school_keys AS (
  SELECT id FROM (SELECT id FROM public.school_standard
    WHERE verification_status = '已核验' ORDER BY id LIMIT 6) s
  UNION SELECT id FROM (SELECT id FROM public.school_standard
    WHERE verification_status = '已合并' ORDER BY id LIMIT 1) s
),
major_keys AS (
  SELECT id FROM (SELECT id FROM public.major_standard
    WHERE verification_status = '已核验' ORDER BY id LIMIT 3) s
  UNION SELECT id FROM (SELECT id FROM public.major_standard
    WHERE verification_status = '已合并' ORDER BY id LIMIT 1) s
),
mapping_ids AS (
  SELECT id FROM (SELECT id FROM public.name_mapping
    WHERE company_id IN (SELECT id FROM company_keys)
       OR school_id IN (SELECT id FROM school_keys)
       OR major_id IN (SELECT id FROM major_keys)
    ORDER BY entity_type, id LIMIT 80) s
  UNION SELECT id FROM (SELECT id FROM public.name_mapping
    WHERE entity_type = 'company' AND original_database_id IS NULL
    ORDER BY id LIMIT 5) s
  UNION SELECT id FROM (SELECT id FROM public.name_mapping
    WHERE processing_status = '待确认' ORDER BY id LIMIT 5) s
),
mapping_sample AS (
  SELECT id, batch_no, source_id, source_file, source_sheet, source_row,
         original_database_id, entity_type, item_id, item_no, raw_name,
         cleaned_name, company_id, school_id, major_id, processing_status,
         attributes->>'source_namespace' AS source_namespace,
         attributes->>'source_record_id' AS source_record_id
  FROM public.name_mapping WHERE id IN (SELECT id FROM mapping_ids)
),
school_selection AS (
  SELECT id FROM school_keys
  UNION SELECT school_id FROM mapping_sample WHERE school_id IS NOT NULL
),
major_selection AS (
  SELECT id FROM major_keys
  UNION SELECT major_id FROM mapping_sample WHERE major_id IS NOT NULL
)
SELECT jsonb_build_object(
  'format_version', 1, 'captured_at', now(), 'project', 'company-resolution-test',
  'company_standard', (SELECT jsonb_agg(to_jsonb(s) ORDER BY s.id) FROM (
    SELECT id, standard_name, short_name, former_names, verification_status
    FROM public.company_standard WHERE id IN (SELECT id FROM company_keys)
      OR id IN (SELECT company_id FROM mapping_sample WHERE company_id IS NOT NULL)
  ) s),
  'school_standard', (SELECT jsonb_agg(to_jsonb(s) ORDER BY s.id) FROM (
    SELECT id, standard_name, short_name, former_names, verification_status,
           attributes->>'merged_into_id' AS merged_into_id
    FROM public.school_standard WHERE id IN (SELECT id FROM school_selection)
      OR id::text IN (SELECT attributes->>'merged_into_id'
        FROM public.school_standard WHERE id IN (SELECT id FROM school_selection))
  ) s),
  'major_standard', (SELECT jsonb_agg(to_jsonb(s) ORDER BY s.id) FROM (
    SELECT id, standard_name, verification_status,
           attributes->>'merged_into_id' AS merged_into_id
    FROM public.major_standard WHERE id IN (SELECT id FROM major_selection)
      OR id::text IN (SELECT attributes->>'merged_into_id'
        FROM public.major_standard WHERE id IN (SELECT id FROM major_selection))
  ) s),
  'name_mapping', (SELECT jsonb_agg(to_jsonb(s) ORDER BY s.id) FROM mapping_sample s),
  'company_relation', (SELECT jsonb_agg(to_jsonb(s) ORDER BY s.id) FROM relation_sample s)
) AS sample;
