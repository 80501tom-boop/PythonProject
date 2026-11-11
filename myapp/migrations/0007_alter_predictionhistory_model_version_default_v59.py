from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("myapp", "0006_alter_predictionhistory_model_version_default"),
    ]

    operations = [
        migrations.AlterField(
            model_name="predictionhistory",
            name="model_version",
            field=models.CharField(
                default="V5.9-FORWARD",
                max_length=50,
                verbose_name="模型版本",
            ),
        ),
    ]
