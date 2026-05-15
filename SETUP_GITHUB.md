# Публикация на GitHub (аккаунт lacriwo)

В этой среде `gh` не авторизован. Выполните на своём ПК в каталоге репозитория:

```powershell
cd C:\Users\lacri\bitrix-feed-apartments-sync
gh auth login
gh repo create lacriwo/bitrix-feed-apartments-sync --public --source=. --remote origin --push
```

Если репозиторий уже создан пустым на GitHub:

```powershell
git remote add origin https://github.com/lacriwo/bitrix-feed-apartments-sync.git
git push -u origin main
```

После первого пуша откройте **Actions** и убедитесь, что workflow включён. При желании запустите вручную **Sync apartments from Bitrix feed**.
