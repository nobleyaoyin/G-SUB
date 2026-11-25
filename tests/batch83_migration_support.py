"""Apply the explicit prospective distribution cutover to disposable fixtures."""
from importlib import import_module

def migrate_rounds(path):
    import_module('migrations.031_editor_invitation_revocation').migrate(path)
    import_module('migrations.032_editor_distribution_rounds').migrate(path)

def bootstrap_prospective_distribution(path):
    """Install distribution prerequisites through 032 on a synthetic database."""
    for name in ('021_document_distribution', '025_automatic_distribution',
                 '026_controlled_source_policy', '027_source_grant_provenance'):
        import_module('migrations.' + name).migrate(path)
    from scripts.upgrade_automatic_distribution import upgrade
    upgrade(path, through_rounds=True)
