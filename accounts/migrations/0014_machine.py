from django.db import migrations, models
import django.db.models.deletion
from django.conf import settings


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0013_push_token_default_empty'),
    ]

    operations = [
        migrations.CreateModel(
            name='Machine',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('machine_type', models.CharField(max_length=30, choices=[
                    ('drone', 'Drone'),
                    ('tractor', 'Tractor'),
                    ('harvester', 'Harvester'),
                    ('rotavator', 'Rotavator'),
                    ('seed_drill', 'Seed Drill'),
                    ('water_tanker', 'Water Tanker'),
                    ('cultivator', 'Cultivator'),
                    ('fertilizer_sprayer', 'Fertilizer Sprayer'),
                ])),
                ('model_name', models.CharField(max_length=100, blank=True)),
                ('registration_number', models.CharField(max_length=50, blank=True)),
                ('is_active', models.BooleanField(default=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('operator', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='machines',
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={'ordering': ['machine_type']},
        ),
    ]
