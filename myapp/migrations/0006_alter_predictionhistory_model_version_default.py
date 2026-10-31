from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("myapp", "0005_predictionhistory_uniq_pred_symbol_model_data_date"),
    ]

    operations = [
        migrations.AlterField(
            model_name="predictionhistory",
            name="model_version",
            field=models.CharField(
                default="V5.8-FORWARD",
                max_length=50,
                verbose_name="模型版本",
            ),
        ),
    ]
