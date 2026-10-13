"""Export trained Spark pipeline results to JSON files for MongoDB import.

Call this from the Kaggle notebook after ALS, re-ranker, FP-Growth, K-Means,
`user_features`, mappings, and Train DataFrames have been created.
"""

from __future__ import annotations

from pathlib import Path

from pyspark.ml.functions import vector_to_array
from pyspark.sql import Window, functions as F


def export_kaggle_results(
    output_dir: str,
    als_model,
    reranker_model,
    assembler,
    user_features,
    user_mapping,
    product_mapping,
    product_metadata,
    association_rules,
    item_clusters,
    train,
    als_candidate_k: int = 50,
    user_recommendation_k: int = 30,
    cluster_top_k: int = 100,
) -> None:
    """Write four Spark JSON directories matching the online Mongo schema."""
    root = str(Path(output_dir))
    users = user_mapping.select("user_idx").distinct()

    raw_candidates = als_model.recommendForUserSubset(users, als_candidate_k)
    candidates = (
        raw_candidates
        .select("user_idx", F.explode("recommendations").alias("rec"))
        .select(
            "user_idx",
            F.col("rec.item_idx").cast("int").alias("item_idx"),
            F.col("rec.rating").cast("double").alias("als_score"),
        )
    )

    scored = (
        candidates
        .join(product_metadata, "item_idx", "inner")
        .join(user_features, "user_idx", "inner")
    )
    scored = (
        reranker_model.transform(assembler.transform(scored))
        .withColumn("purchase_prob", vector_to_array("probability")[1])
    )
    rank_window = Window.partitionBy("user_idx").orderBy(
        F.col("purchase_prob").desc(), F.col("als_score").desc(), F.col("item_idx").asc()
    )
    ranked = (
        scored.withColumn("rank", F.row_number().over(rank_window))
        .filter(F.col("rank") <= user_recommendation_k)
    )

    recommendations = (
        ranked.join(user_mapping.select("user_idx", "user_id"), "user_idx", "inner")
        .groupBy("user_id")
        .agg(
            F.sort_array(
                F.collect_list(F.struct(
                    F.col("rank").alias("rank"),
                    F.col("product_id").cast("string").alias("product_id"),
                    F.col("item_idx").cast("int").alias("item_idx"),
                    F.col("brand").alias("brand"),
                    F.col("category_code").alias("category_code"),
                    F.col("avg_price").cast("double").alias("avg_price"),
                    F.col("als_score").cast("double").alias("als_score"),
                    F.col("purchase_prob").cast("double").alias("purchase_prob"),
                ))
            ).alias("recommendations")
        )
    )
    recommendations.write.mode("overwrite").json(f"{root}/user_recommendations")

    singleton_rules = (
        association_rules
        .filter(F.size("antecedent") == 1)
        .select(
            F.element_at("antecedent", 1).cast("int").alias("antecedent_idx"),
            F.explode("consequent").cast("int").alias("consequent_idx"),
            F.col("confidence").cast("double").alias("confidence"),
            F.col("lift").cast("double").alias("lift"),
        )
    )
    antecedent_products = product_metadata.select(
        F.col("item_idx").alias("antecedent_idx"),
        F.col("product_id").cast("string").alias("antecedent_product_id"),
    )
    consequent_products = product_metadata.select(
        F.col("item_idx").alias("consequent_idx"),
        F.col("product_id").cast("string").alias("consequent_product_id"),
        "brand", "category_code", F.col("avg_price").cast("double").alias("avg_price"),
    )
    association_docs = (
        singleton_rules
        .join(antecedent_products, "antecedent_idx", "inner")
        .join(consequent_products, "consequent_idx", "inner")
        .groupBy("antecedent_idx", "antecedent_product_id")
        .agg(F.collect_list(F.struct(
            "consequent_idx", "consequent_product_id", "brand", "category_code",
            "avg_price", "confidence", "lift",
        )).alias("consequents"))
    )
    association_docs.write.mode("overwrite").json(f"{root}/item_associations")

    metadata_docs = (
        product_metadata
        .join(item_clusters.select("item_idx", "cluster_id"), "item_idx", "inner")
        .select(
            F.col("product_id").cast("string").alias("product_id"),
            F.col("item_idx").cast("int").alias("item_idx"),
            "brand", "category_code",
            F.col("avg_price").cast("double").alias("avg_price"),
            F.col("cluster_id").cast("int").alias("cluster_id"),
        )
    )
    metadata_docs.write.mode("overwrite").json(f"{root}/product_metadata")

    popularity = train.groupBy("item_idx").agg(
        F.sum("purchase_count").cast("long").alias("purchase_count")
    )
    clustered_products = (
        item_clusters.join(product_metadata, "item_idx", "inner")
        .join(popularity, "item_idx", "left")
        .fillna({"purchase_count": 0})
    )
    cluster_window = Window.partitionBy("cluster_id").orderBy(
        F.col("purchase_count").desc(), F.col("item_idx").asc()
    )
    cluster_top = (
        clustered_products
        .withColumn("_rank", F.row_number().over(cluster_window))
        .filter(F.col("_rank") <= cluster_top_k)
        .groupBy("cluster_id")
        .agg(F.collect_list(F.struct(
            F.col("item_idx").cast("int").alias("item_idx"),
            F.col("product_id").cast("string").alias("product_id"),
            "brand",
            F.col("avg_price").cast("double").alias("avg_price"),
            F.col("purchase_count").alias("purchase_count"),
        )).alias("top_popular_items"))
    )
    cluster_profiles = clustered_products.groupBy("cluster_id").agg(
        F.avg("avg_price").cast("double").alias("cluster_avg_price")
    )
    cluster_docs = cluster_profiles.join(cluster_top, "cluster_id", "left")
    cluster_docs.write.mode("overwrite").json(f"{root}/cluster_fallbacks")

    print(f"Spark JSON exports written under {root}")
