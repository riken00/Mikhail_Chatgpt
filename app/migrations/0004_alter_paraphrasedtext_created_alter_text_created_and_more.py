# Generated by Django 4.1.6 on 2023-02-19 19:38

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('app', '0003_user_details_paraphrasedtext_created_and_more'),
    ]

    operations = [
        migrations.AlterField(
            model_name='paraphrasedtext',
            name='created',
            field=models.DateTimeField(auto_now_add=True, verbose_name='Created'),
        ),
        migrations.AlterField(
            model_name='text',
            name='created',
            field=models.DateTimeField(auto_now_add=True, verbose_name='Created'),
        ),
        migrations.AlterField(
            model_name='user_details',
            name='created',
            field=models.DateTimeField(auto_now_add=True, verbose_name='Created'),
        ),
    ]
