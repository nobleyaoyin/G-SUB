"""Small, read-only metadata projection for an authorized editor invitation."""
from sqlalchemy.exc import SQLAlchemyError
from app.ai_prescreening_read import list_manuscript_ai_reports


def invitation_metadata(db, manuscript):
    """Return only optional scalar metadata, never source text or report contents.

    The caller must first verify invitation ownership, state and manuscript scope.
    Advisory counts describe the latest recorded author-submission snapshot, not
    necessarily the document currently being edited.
    """
    result = {'subject': None, 'keywords': None, 'word_count': None,
              'word_count_source': None, 'table_count': None, 'figure_count': None,
              'excerpt': None}
    try:
        reports = list_manuscript_ai_reports(db, manuscript.manuscript_id)
    except (SQLAlchemyError, ValueError):
        return result
    if not reports:
        return result
    latest = reports[0]
    analysis = latest.get('analysis')
    if (latest.get('review_round') != manuscript.review_round or latest.get('status') != 'completed'
            or not isinstance(analysis, dict) or analysis.get('engine') != 'local_rules_v1'
            or analysis.get('advisory_only') is not True):
        return result
    fmt = latest.get('file_format')
    count = analysis.get('word_count')
    if fmt not in ('txt', 'docx') or analysis.get('format') != fmt or type(count) is not int or count < 0 or count > 2_000_000:
        return result
    result['word_count'] = count
    result['word_count_source'] = f'Advisory local {fmt.upper()} analysis of latest author-submission snapshot, round {manuscript.review_round}'
    return result
