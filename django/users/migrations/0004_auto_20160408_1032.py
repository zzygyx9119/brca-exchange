# -*- coding: utf-8 -*-
# Generated by Django 1.9.4 on 2016-04-08 10:32
from __future__ import unicode_literals

from django.db import migrations, models
import django.utils.timezone


class Migration(migrations.Migration):

    dependencies = [
        ('users', '0003_myuser_has_image'),
    ]

    operations = [
        migrations.AddField(
            model_name='myuser',
            name='activation_key',
            field=models.CharField(blank=True, max_length=40),
        ),
        migrations.AddField(
            model_name='myuser',
            name='key_expires',
            field=models.DateTimeField(default=django.utils.timezone.now),
        ),
    ]
