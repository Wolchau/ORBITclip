"""Regression for Qt clicked(bool) overriding a closure's default category ID."""
import tempfile
from pathlib import Path
from orbit_categories import CategoryModel, category_click_handler, WheelQueue
from kinetic_clipboard import ClipboardVault

def test_category_navigation():
    with tempfile.TemporaryDirectory() as folder:
        vault = ClipboardVault(Path(folder) / 'history.json')
        text = vault.add('Небольшая заметка')
        sql = vault.add('SELECT * FROM orders;')
        link = vault.add('https://example.org/page')
        model = CategoryModel()
        custom = model.add('Рабочее', 'document')
        vault.describe(text['id'], title='Моя заметка', category=custom['id'])
        selected = ['all']
        actions = {category['id']: category_click_handler(category['id'],
                   lambda cat_id: selected.__setitem__(0, cat_id))
                   for category in model.visible_categories()}
        for category_id, expected in [('all', 3), ('text', 1), ('sql', 1),
                                      ('link', 1), ('code', 1), ('favorites', 0),
                                      (custom['id'], 1)]:
            # Qt sends checked=False on click. Previously this made cid=False.
            actions[category_id](False)
            assert selected[0] == category_id, (category_id, selected[0])
            items = [item for item in vault.items if model.matches(item, selected[0])]
            assert len(items) == expected, (category_id, items)
            # A checkable button would send True; that must not override the ID.
            actions[category_id](True)
            assert selected[0] == category_id
        # Invalid data must not crash the window.
        assert not model.matches(sql, False)
        assert not model.matches(sql, True)
        assert not model.matches(sql, None)
        assert not model.matches(sql, 7)
        assert len(WheelQueue().candidates(vault.items, model, 'all')) == 3

if __name__ == '__main__':
    test_category_navigation()
    print('PASS: Qt clicked(bool), built-in filters, custom categories, invalid IDs')
