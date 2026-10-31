"""Test whether a trailing block can follow complete neighboring columns."""


def overlap_x(a, b):
    return min(a[2], b[2]) > max(a[0], b[0])


def reorder(groups):
    result = list(groups)
    index = 0
    while index < len(result):
        current = result[index]["box"]
        later = [
            (j, g)
            for j, g in enumerate(result[index + 1 :], index + 1)
            if not overlap_x(current, g["box"])
        ]
        clusters = []
        for j, g in later:
            hits = [
                c
                for c in clusters
                if any(overlap_x(g["box"], item["box"]) for _, item in c)
            ]
            if not hits:
                clusters.append([(j, g)])
            else:
                hits[0].append((j, g))
                for other in hits[1:]:
                    hits[0].extend(other)
                    clusters.remove(other)
        # A second column has multiple lines, all above this trailing block.
        prior = [
            g
            for g in result[:index]
            if overlap_x(current, g["box"]) and g["box"][3] <= current[1]
        ]

        def vertically_aligned(first, second):
            return min(first[3], second[3]) > max(first[1], second[1]) and max(
                first[3] - first[1], second[3] - second[1]
            ) <= 2 * min(first[3] - first[1], second[3] - second[1])

        eligible = [
            c
            for c in clusters
            if len(c) >= 2
            and all(
                item["box"][3] <= current[1]
                and any(ch.isalpha() for ch in item["text"])
                for _, item in c
            )
            and all(
                any(vertically_aligned(item["box"], p["box"]) for p in prior)
                for _, item in c
            )
        ]
        if eligible:
            last = max(j for c in eligible for j, _ in c)
            result.insert(last, result.pop(index))
        else:
            index += 1
    return result
